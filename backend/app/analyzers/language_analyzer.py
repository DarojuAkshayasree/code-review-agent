import re
from typing import Any


SUPPORTED_LANGUAGES = {
    "python", "java", "javascript", "typescript", "c", "cpp", "csharp", "go"
}


class LanguageAnalyzer:
    """Conservative text-pattern checks for languages without a parser here."""

    def analyze(self, code: str, language: str) -> list[dict[str, Any]]:
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        if language == "python":
            return []

        findings: list[dict[str, Any]] = []

        def add(identifier: str, severity: str, category: str, title: str, description: str, suggestion: str, evidence: str) -> None:
            findings.append({
                "id": identifier,
                "severity": severity,
                "category": category,
                "title": title,
                "description": description,
                "suggestion": suggestion,
                "evidence": [evidence],
                "tool": "pattern_checks",
                "team_rule_id": None,
            })

        secret_pattern = re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"]{4,}['\"]"
        )
        secret_match = secret_pattern.search(code)
        if secret_match:
            add("hardcoded-secret", "critical", "security", "Possible hardcoded secret", "A credential-like value appears to be assigned directly in source code.", "Load secrets from a protected configuration or secret manager and rotate any exposed credential.", secret_match.group(0))

        if language in {"javascript", "typescript"}:
            if re.search(r"\bconsole\s*\.\s*log\s*\(", code):
                add("debug-console", "low", "debugging", "Debug logging left in code", "A console.log call is present.", "Remove temporary logging or replace it with the application's structured logger.", "console.log")
            unsafe = re.search(r"\beval\s*\(|\binnerHTML\s*=", code)
            if unsafe:
                add("unsafe-js-pattern", "high", "security", "Potentially unsafe dynamic code or HTML", "The code uses eval or assigns to innerHTML, which can expose injection risks.", "Avoid evaluating dynamic strings and use safe DOM APIs or framework rendering.", unsafe.group(0))
            if re.search(r"\b(?:router|app)\s*\.\s*(?:get|post|put|delete|patch)\s*\([^;{}]*\{[\s\S]{0,600}?\b(?:query|execute|findOne|findMany)\s*\(", code, re.I):
                add("database-in-route", "high", "architecture", "Database access in route or controller", "A route handler appears to issue a database operation directly.", "Move database access into a repository or service and keep the route focused on HTTP concerns.", "database call inside route handler")

        elif language == "java":
            if re.search(r"\bSystem\s*\.\s*out\s*\.\s*(?:print|println)\s*\(", code):
                add("debug-system-out", "low", "debugging", "Debug output left in code", "System.out is used for application output.", "Use an application logger and remove temporary debug output.", "System.out")
            if re.search(r"\bcatch\s*\(\s*(?:Exception|Throwable)\b", code):
                add("broad-java-exception", "medium", "reliability", "Overly broad exception handling", "A catch block handles Exception or Throwable broadly.", "Catch the expected exception types and handle them explicitly.", "catch (Exception/Throwable)")
            controller = re.search(r"(?is)(?:@RestController|@Controller|class\s+\w*Controller\b)[\s\S]{0,2500}", code)
            if controller and re.search(r"\b(?:jdbcTemplate|entityManager)\b|\.executeQuery\s*\(|\.prepareStatement\s*\(", controller.group(0)):
                add("database-in-controller", "high", "architecture", "Database access in controller", "A controller appears to call a database API directly.", "Move database access behind a repository or service and inject that abstraction into the controller.", "database call in controller")

        elif language in {"c", "cpp"}:
            unsafe = re.search(r"\b(?:gets|strcpy|strcat|sprintf)\s*\(", code)
            if unsafe:
                add("unsafe-c-function", "high", "security", "Potentially unsafe C/C++ function", "A legacy unbounded input or string function is present.", "Use a bounded alternative and validate input lengths.", unsafe.group(0))
            if re.search(r"\b(?:printf|puts)\s*\(|\bstd::cout\s*<<", code):
                add("debug-c-output", "low", "debugging", "Debug output may be present", "A direct console output statement is present.", "Remove temporary output or route diagnostics through the project's logging mechanism.", "printf/puts/std::cout")
            if re.search(r"\bmalloc\s*\(", code) and not re.search(r"\bfree\s*\(", code):
                add("possible-unreleased-memory", "medium", "resource_management", "Possible unreleased allocation", "The file allocates memory with malloc but no free call was found in the submitted text.", "Verify ownership and release the allocation on all paths, or use an owning C++ type.", "malloc without a visible free")

        elif language == "csharp":
            if re.search(r"\bConsole\s*\.\s*Write(?:Line)?\s*\(", code):
                add("debug-console-write", "low", "debugging", "Debug output left in code", "Console.Write or Console.WriteLine is present.", "Use the application's logging abstraction and remove temporary output.", "Console.WriteLine")
            if re.search(r"\bcatch\s*\(\s*Exception\b", code):
                add("broad-csharp-exception", "medium", "reliability", "Overly broad exception handling", "A catch block handles Exception broadly.", "Catch expected exception types and handle them explicitly.", "catch (Exception)")
            if re.search(r"\b(?:SqlConnection|SqlCommand|DbContext)\b", code) and re.search(r"\bclass\s+\w*Controller\b", code):
                add("database-in-controller", "high", "architecture", "Database access in controller", "A controller appears to create or use database access directly.", "Move database access behind a repository or service.", "database API in controller")

        elif language == "go":
            if re.search(r"\bfmt\s*\.\s*Print(?:f|ln)?\s*\(", code):
                add("debug-fmt-print", "low", "debugging", "Debug output left in code", "fmt.Print is used in application code.", "Use structured logging and remove temporary debug output.", "fmt.Println")
            if re.search(r"http\.HandleFunc|http\.HandlerFunc", code) and re.search(r"\b(?:db|database|sqlDB)\s*\.\s*(?:Query|Exec|QueryRow)", code):
                add("database-in-handler", "high", "architecture", "Database access in HTTP handler", "An HTTP handler appears to query the database directly.", "Move database operations into a repository or service used by the handler.", "database call in HTTP handler")

        return findings