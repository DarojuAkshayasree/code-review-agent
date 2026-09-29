import json
from typing import Any

from app.analyzers.language_analyzer import LanguageAnalyzer, SUPPORTED_LANGUAGES
from app.analyzers.python_analyzer import PythonAnalyzer
from app.config import ai_configured, settings
from app.memory.memory_service import MemoryService

try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None


class CodeReviewAgent:
    def __init__(self, memory_service: MemoryService | None = None):
        self.memory_service = memory_service or MemoryService()
        self.python_analyzer = PythonAnalyzer()
        self.language_analyzer = LanguageAnalyzer()

    def review_code(self, code: str, language: str = "python", filename: str = "") -> dict[str, Any]:
        if not code or not code.strip():
            raise ValueError("Code cannot be empty.")
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")

        static_findings = self.python_analyzer.analyze(code) if language == "python" else self.language_analyzer.analyze(code, language)
        relevant_rules = self.memory_service.get_relevant_rules(code)
        similar_reviews = self.memory_service.get_similar_reviews(code)
        ai_findings = self._llm_review(code, language, relevant_rules, similar_reviews, static_findings)

        merged_findings = self._merge_findings(static_findings, ai_findings)
        if not merged_findings:
            merged_findings = [{
                "id": "no-issues",
                "severity": "suggestion",
                "category": "general",
                "title": "No major issues detected",
                "description": "No obvious problems were found in the provided code.",
                "suggestion": "Continue with the review and consider the maintainability checks below.",
                "evidence": [],
                "team_rule_id": None,
            }]

        memory_used = []
        for rule in relevant_rules:
            memory_used.append({"rule": rule["text"], "source": "team_standard"})
        for review in similar_reviews:
            memory_used.append({"rule": review.get("summary", "Similar prior review"), "source": "previous_review"})

        score = self._calculate_score(merged_findings)
        summary = self._summarize(merged_findings)
        result = {
            "review_id": self._new_id(),
            "filename": filename,
            "language": language,
            "summary": summary,
            "score": score,
            "findings": merged_findings,
            "memory_used": memory_used,
            "code": code,
        }
        self.memory_service.record_review(result)
        return result

    def _llm_review(self, code: str, language: str, relevant_rules: list[dict], similar_reviews: list[dict], static_findings: list[dict]) -> list[dict[str, Any]]:
        if not ai_configured() or AzureOpenAI is None:
            return self._deterministic_fallback(code, relevant_rules, similar_reviews, static_findings)

        system_prompt = self._build_system_prompt(language, relevant_rules, similar_reviews)
        try:
            client = AzureOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
            response = client.chat.completions.create(
                model=settings.AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": code},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = response.choices[0].message.content
            if not content:
                return []
            payload = json.loads(content)
            return payload.get("findings", [])
        except Exception:
            return self._deterministic_fallback(code, relevant_rules, similar_reviews, static_findings)

    def _deterministic_fallback(self, code: str, relevant_rules: list[dict], similar_reviews: list[dict], static_findings: list[dict]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        lowered = code.lower()

        has_architecture_finding = any(item.get("category") == "architecture" for item in static_findings)
        if not has_architecture_finding and any(marker in lowered for marker in ("db.query", "cursor.execute", "session.execute", "database.query")):
            findings.append({
                "id": "fallback-db-access",
                "severity": "high",
                "category": "architecture",
                "title": "Database access in controller layer",
                "description": "The route or controller appears to perform database access directly.",
                "suggestion": "Move this logic behind a repository or service layer so controllers stay focused on request handling.",
                "evidence": ["db.query detected in controller-style function"],
                "team_rule_id": "team-rule",
            })

        if "auth" in lowered and "service" not in lowered:
            findings.append({
                "id": "fallback-auth",
                "severity": "medium",
                "category": "architecture",
                "title": "Authentication logic may belong in service layer",
                "description": "Authentication-related behavior was detected without an explicit service boundary.",
                "suggestion": "Move auth orchestration into the service layer for consistent handling.",
                "evidence": ["auth logic detected"],
                "team_rule_id": "team-rule",
            })

        for finding in findings + static_findings:
            if finding.get("category") != "architecture":
                continue
            for rule in relevant_rules:
                rule_text = rule["text"]
                if any(term in rule_text.lower() for term in ("database", "repository", "service")):
                    finding["description"] += f" Your team standard says: {rule_text}"
                    finding["team_rule_id"] = rule["id"]
                    break

        if similar_reviews:
            prior = similar_reviews[0]
            database_rule = next((
                rule for rule in relevant_rules
                if any(term in rule["text"].lower() for term in ("database", "repository", "service"))
            ), None)
            database_issue = any(
                finding.get("category") == "architecture" and "database" in finding.get("title", "").lower()
                for finding in static_findings
            )
            if database_rule and database_issue:
                title = "Your team has addressed a similar issue before"
                description = (
                    "Your team previously established that database access should be handled through the "
                    f"Repository/Service layer. A similar issue was identified in an earlier review: {prior.get('summary', 'Earlier review')}."
                )
            else:
                title = "A similar issue was found previously"
                description = f"A similar review was recorded earlier: {prior.get('summary', 'Earlier review')}."
            findings.append({
                "id": "fallback-memory",
                "severity": "medium",
                "category": "team_memory",
                "title": title,
                "description": description,
                "suggestion": "Review the earlier recommendation and reuse the same architecture pattern.",
                "evidence": [f"Review {prior.get('id', '')}"],
                "team_rule_id": None,
            })

        return findings + static_findings

    def _merge_findings(self, static_findings: list[dict], ai_findings: list[dict]) -> list[dict[str, Any]]:
        merged = []
        seen = set()
        for finding in static_findings + ai_findings:
            identifier = finding.get("id") or finding.get("title")
            if identifier in seen:
                continue
            seen.add(identifier)
            merged.append(finding)
        return merged

    def _build_system_prompt(self, language: str, relevant_rules: list[dict], similar_reviews: list[dict]) -> str:
        rules_text = "\n".join(rule["text"] for rule in relevant_rules) if relevant_rules else "no_relevant_memory"
        reviews_text = "\n".join(
            f"Review {review.get('id', 'unknown')}: {review.get('summary', '')}"
            for review in similar_reviews
        ) if similar_reviews else "no_relevant_memory"

        return (
            f"You are an AI code review agent reviewing {language} code for a software development team. "
            "Use the team rules and prior review memory only as supporting context and never invent rules. "
            f"Relevant team rules:\n{rules_text}\n\n"
            f"Previous relevant reviews:\n{reviews_text}\n\n"
            "Return STRICT JSON with a 'findings' array. Each finding must include: "
            "id, severity, category, title, description, suggestion, evidence, team_rule_id. "
            "If no memory matches, explicitly return 'no_relevant_memory' in the relevant fields."
        )

    def _calculate_score(self, findings: list[dict]) -> int:
        if not findings:
            return 100
        penalty = 0
        for item in findings:
            severity = item.get("severity", "low").lower()
            if severity == "critical":
                penalty += 25
            elif severity == "high":
                penalty += 18
            elif severity == "medium":
                penalty += 12
            elif severity == "low":
                penalty += 6
            else:
                penalty += 2
        return max(0, min(100, 100 - penalty))

    def _summarize(self, findings: list[dict]) -> str:
        if not findings:
            return "No issues found."
        top = findings[0]
        return f"{len(findings)} issue(s) detected. Most relevant: {top.get('title', 'Review item')}"

    def _new_id(self) -> str:
        import uuid
        return str(uuid.uuid4())
