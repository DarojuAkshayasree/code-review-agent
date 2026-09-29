import ast
import re
from typing import Any


class PythonAnalyzer:
    def analyze(self, code: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return [{
                "id": "syntax-error",
                "severity": "critical",
                "category": "syntax",
                "title": "Invalid Python syntax",
                "description": f"Python could not be parsed: {exc.msg}",
                "suggestion": "Fix the syntax error before code review continues.",
                "evidence": exc.msg,
                "tool": "python_ast",
                "team_rule_id": None,
            }]

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_route_handler(node):
                    route_violations = self._find_db_access_in_function(node)
                    if route_violations:
                        findings.append({
                            "id": f"architecture-{node.lineno}",
                            "severity": "high",
                            "category": "architecture",
                            "title": "Database access in controller or route layer",
                            "description": "This endpoint performs a database query directly instead of delegating to repository or service logic.",
                            "suggestion": "Move the database interaction into a Repository or Service layer and keep the controller focused on request/response flow.",
                            "evidence": route_violations,
                            "tool": "python_ast",
                            "team_rule_id": None,
                        })
                if self._has_missing_type_hints(node):
                    findings.append({
                        "id": f"types-{node.lineno}",
                        "severity": "low",
                        "category": "maintainability",
                        "title": "Missing type hints",
                        "description": f"Function '{node.name}' does not declare explicit type hints for arguments and/or return values.",
                        "suggestion": "Add type hints to improve readability, maintainability, and editor tooling.",
                        "evidence": f"Function {node.name} is missing type annotations",
                        "tool": "python_ast",
                        "team_rule_id": None,
                    })

        duplicate_imports = self._check_duplicate_imports(tree)
        if duplicate_imports:
            findings.append({
                "id": "duplicate-imports",
                "severity": "low",
                "category": "maintainability",
                "title": "Possible duplicate import usage",
                "description": "The file appears to import the same dependency more than once, which can be cleaned up.",
                "suggestion": "Consolidate repeated imports to keep the module easier to maintain.",
                "evidence": duplicate_imports,
                "tool": "python_ast",
                "team_rule_id": None,
            })

        imported_names = []
        loaded_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend((alias.asname or alias.name.split(".")[0], alias.name, node.lineno) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names.extend((alias.asname or alias.name, f"{node.module}.{alias.name}", node.lineno) for alias in node.names if alias.name != "*")
        unused_imports = [name for local_name, name, _ in imported_names if local_name not in loaded_names]
        if unused_imports:
            findings.append({
                "id": "unused-imports",
                "severity": "low",
                "category": "maintainability",
                "title": "Possible unused imports",
                "description": "Some imported names are not referenced in this file.",
                "suggestion": "Remove unused imports after confirming they are not needed for side effects.",
                "evidence": unused_imports,
                "tool": "python_ast",
                "team_rule_id": None,
            })

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is not None and any(
                isinstance(part, ast.Name) and part.id in {"Exception", "BaseException"}
                for part in ast.walk(node.type)
            ):
                findings.append({
                    "id": f"broad-exception-{node.lineno}",
                    "severity": "medium",
                    "category": "reliability",
                    "title": "Overly broad exception handling",
                    "description": "A handler catches Exception or BaseException broadly.",
                    "suggestion": "Catch expected exception types and handle them explicitly.",
                    "evidence": f"Broad exception handler at line {node.lineno}",
                    "tool": "python_ast",
                    "team_rule_id": None,
                })
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                findings.append({
                    "id": f"debug-print-{node.lineno}",
                    "severity": "low",
                    "category": "debugging",
                    "title": "Debug print left in code",
                    "description": "A print call is present in the submitted code.",
                    "suggestion": "Remove temporary output or use the application's logging framework.",
                    "evidence": f"print call at line {node.lineno}",
                    "tool": "python_ast",
                    "team_rule_id": None,
                })

        secret_match = re.search(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*=\s*['\"][^'\"]{4,}['\"]", code)
        if secret_match:
            findings.append({
                "id": "hardcoded-secret",
                "severity": "critical",
                "category": "security",
                "title": "Possible hardcoded secret",
                "description": "A credential-like value appears to be assigned directly in source code.",
                "suggestion": "Load secrets from protected configuration and rotate any exposed credential.",
                "evidence": secret_match.group(0),
                "tool": "python_ast",
                "team_rule_id": None,
            })

        return findings

    def _is_route_handler(self, node: ast.AST) -> bool:
        for decorator in getattr(node, "decorator_list", []):
            if isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Attribute):
                    name = func.attr.lower()
                elif isinstance(func, ast.Name):
                    name = func.id.lower()
                else:
                    name = ""
                if any(marker in name for marker in ["route", "get", "post", "put", "delete", "patch"]):
                    return True
            elif isinstance(decorator, ast.Attribute):
                if decorator.attr.lower() in {"route", "get", "post", "put", "delete", "patch"}:
                    return True
        return False

    def _find_db_access_in_function(self, node: ast.AST) -> list[str]:
        findings = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = self._call_name(child)
                if func_name in {"db.query", "execute", "session.execute", "cursor.execute", "query"} or "db.query" in func_name:
                    findings.append(func_name)
        return findings

    def _call_name(self, node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Attribute):
            base = self._call_name_from_expr(func.value)
            return f"{base}.{func.attr}" if base else func.attr
        if isinstance(func, ast.Name):
            return func.id
        return "call"

    def _call_name_from_expr(self, expr: ast.AST) -> str:
        if isinstance(expr, ast.Attribute):
            base = self._call_name_from_expr(expr.value)
            return f"{base}.{expr.attr}" if base else expr.attr
        if isinstance(expr, ast.Name):
            return expr.id
        return ""

    def _has_missing_type_hints(self, node: ast.AST) -> bool:
        if not node.args.args and not node.returns:
            return False
        arg_annotations = [arg.annotation is not None for arg in node.args.args]
        has_vararg = node.args.vararg is not None and node.args.vararg.annotation is not None
        has_kwarg = node.args.kwarg is not None and node.args.kwarg.annotation is not None
        has_return = node.returns is not None
        is_missing = (len(arg_annotations) > 0 and not all(arg_annotations)) or (not has_return and node.body)
        if node.args.args and not any(arg_annotations):
            return True
        return is_missing and not (has_vararg and has_kwarg and has_return)

    def _check_duplicate_imports(self, tree: ast.AST) -> list[str]:
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.setdefault(alias.name, 0)
                    imports[alias.name] += 1
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.setdefault(node.module, 0)
                    imports[node.module] += 1
        return [name for name, count in imports.items() if count > 1]
