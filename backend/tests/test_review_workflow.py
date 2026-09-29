import json

import pytest
from fastapi.testclient import TestClient

from app.agents.review_agent import CodeReviewAgent
from app.analyzers.language_analyzer import LanguageAnalyzer
from app.analyzers.python_analyzer import PythonAnalyzer
from app.database import database as database_module
from app.memory.memory_service import MemoryService


@pytest.fixture(autouse=True)
def isolate_test_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "test.sqlite")


def test_database_call_inside_controller_detected():
    code = '''
@app.get("/users")
def get_users():
    users = db.query("SELECT * FROM users")
    return users
'''
    findings = PythonAnalyzer().analyze(code)
    assert any(f["category"] == "architecture" and "Database access" in f["title"] for f in findings)


def test_missing_type_hints_detected():
    code = '''
def get_user(data):
    return data
'''
    findings = PythonAnalyzer().analyze(code)
    assert any(f["category"] == "maintainability" and "Missing type hints" in f["title"] for f in findings)


def test_team_rule_retrieval():
    memory = MemoryService()
    memory.reset_demo_data()
    memory.add_rule("Database calls must not happen directly inside Controllers. Use the Repository/Service layer.", "architecture")
    rules = memory.get_relevant_rules('db.query("SELECT * FROM users")')
    assert rules and any("Database calls" in rule["text"] for rule in rules)


def test_similar_previous_review_retrieval():
    memory = MemoryService()
    memory.reset_demo_data()
    memory.record_review({
        "review_id": "review-100",
        "filename": "users.py",
        "summary": "Controller contained direct database query.",
        "score": 68,
        "code": "db.query(\"SELECT * FROM users\")",
        "findings": [{"title": "Database access in controller"}],
        "memory_used": [],
        "created_at": "2024-01-01T00:00:00Z",
    })
    reviews = memory.get_similar_reviews('db.query("SELECT * FROM users")')
    assert any(review["id"] == "review-100" for review in reviews)


def test_accepting_feedback():
    memory = MemoryService()
    memory.reset_demo_data()
    feedback = memory.record_feedback("review-1", "finding-1", "accepted")
    assert feedback["action"] == "accepted"


def test_memory_persistence():
    memory = MemoryService()
    memory.reset_demo_data()
    memory.add_rule("Use meaningful variable names.", "coding")
    rules = memory.list_rules()
    assert any("meaningful variable names" in rule["text"].lower() for rule in rules)


def test_second_review_uses_previous_memory():
    memory = MemoryService()
    memory.reset_demo_data()
    memory.add_rule("Database calls must not happen directly inside Controllers. Use the Repository/Service layer.", "architecture")
    memory.record_review({
        "review_id": "review-prev",
        "filename": "users.py",
        "summary": "Controller contained database access.",
        "score": 60,
        "code": "db.query(\"SELECT * FROM users\")",
        "findings": [{"title": "Database access in controller"}],
        "memory_used": [{"rule": "Database calls must not happen directly inside Controllers.", "source": "team_standard"}],
        "created_at": "2024-01-01T00:00:00Z",
    })
    agent = CodeReviewAgent(memory)
    result = agent.review_code('''\n@app.get("/users")\ndef get_users():\n    users = db.query("SELECT * FROM users")\n    return users\n''')
    assert result["findings"]
    assert any('database' in str(f.get('description', '')).lower() or 'database access' in str(f.get('title', '')).lower() for f in result["findings"])
    assert result["memory_used"]


def test_invalid_python_code():
    analyzer = PythonAnalyzer()
    findings = analyzer.analyze('def broken(:\n    pass')
    assert findings and findings[0]["category"] == "syntax"


def test_empty_code_rejected():
    agent = CodeReviewAgent(MemoryService())
    try:
        agent.review_code('   ')
        assert False, 'Expected ValueError for empty code.'
    except ValueError:
        pass


def test_multi_language_static_checks_and_repository_delegation():
    analyzer = LanguageAnalyzer()
    cases = [
        ("java", 'class UserController { System.out.println("debug"); catch (Exception ex) {} jdbcTemplate.queryForList(); String password = "demo-secret-12345"; }', {"debugging", "reliability", "architecture", "security"}),
        ("javascript", 'const apiKey = "demo-secret-12345"; app.get("/users", (req, res) => { console.log("debug"); database.query(); });', {"debugging", "architecture", "security"}),
        ("typescript", 'console.log("debug"); eval(input);', {"debugging", "security"}),
        ("c", 'char password[] = "demo-secret-12345"; gets(input); printf("debug");', {"security", "debugging"}),
        ("cpp", 'char* data = (char*)malloc(16); strcpy(data, input); std::cout << data;', {"security", "resource_management", "debugging"}),
        ("csharp", 'class UsersController { SqlConnection connection; Console.WriteLine("debug"); catch (Exception) {} }', {"debugging", "reliability", "architecture"}),
        ("go", 'var password = "demo-secret-12345"; http.HandleFunc("/users", func(w, r) { db.Query("SELECT 1") }); fmt.Println("debug")', {"security", "architecture", "debugging"}),
    ]
    for language, code, expected_categories in cases:
        categories = {finding["category"] for finding in analyzer.analyze(code, language)}
        assert expected_categories <= categories, (language, categories)

    repository_call = "class UserController { userRepository.findAll(); }"
    assert not any(finding["category"] == "architecture" for finding in analyzer.analyze(repository_call, "java"))


def test_accepted_feedback_becomes_team_memory_for_next_review():
    memory = MemoryService()
    memory.reset_demo_data()
    agent = CodeReviewAgent(memory)
    code = '''
@app.get("/users")
def get_users():
    return db.query("SELECT * FROM users")
'''
    first = agent.review_code(code, "python", "users.py")
    architecture = next(item for item in first["findings"] if item["category"] == "architecture")
    feedback = memory.record_feedback(first["review_id"], architecture["id"], "accepted")
    assert feedback["created_rule"]["source"] == "accepted_feedback"

    second = agent.review_code(code.replace("users", "accounts"), "python", "accounts.py")
    assert any("previously established" in item["description"] for item in second["findings"])
    assert any(item["source"] == "previous_review" for item in second["memory_used"])


def test_rejected_feedback_does_not_create_team_rule():
    memory = MemoryService()
    memory.reset_demo_data()
    result = CodeReviewAgent(memory).review_code("print('debug')", "python", "debug.py")
    finding = next(item for item in result["findings"] if item["category"] == "debugging")
    feedback = memory.record_feedback(result["review_id"], finding["id"], "rejected")
    assert feedback["created_rule"] is None
    assert memory.list_rules() == []


def test_review_api_multi_language_feedback_and_stats():
    from app.main import app

    with TestClient(app) as client:
        java = client.post("/api/review", json={
            "code": "@RestController class UserController { JdbcTemplate jdbcTemplate; void get() { jdbcTemplate.queryForList(); } }",
            "language": "java",
            "filename": "UserController.java",
        })
        assert java.status_code == 200
        java_payload = java.json()
        finding = next(item for item in java_payload["findings"] if item["category"] == "architecture")
        accepted = client.post("/api/feedback", json={
            "review_id": java_payload["review_id"],
            "finding_id": finding["id"],
            "action": "accepted",
        })
        assert accepted.status_code == 200
        assert accepted.json()["feedback"]["created_rule"]["source"] == "accepted_feedback"

        javascript = client.post("/api/review", json={
            "code": 'console.log("debug");',
            "language": "javascript",
            "filename": "app.js",
        })
        assert javascript.status_code == 200
        assert any(item["category"] == "debugging" for item in javascript.json()["findings"])

        python_review = client.post("/api/review", json={
            "code": '@app.get("/users")\\ndef get_users():\\n    return db.query("SELECT * FROM users")',
            "language": "python",
            "filename": "users.py",
        })
        assert python_review.status_code == 200
        assert any(item["category"] == "architecture" for item in python_review.json()["findings"])

        stats = client.get("/api/stats").json()
        assert stats["total_reviews"] == 3
        assert stats["team_rules"] == 1
        assert client.get("/api/memory").json()["items"]
