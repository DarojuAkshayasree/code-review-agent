import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from app.database.database import get_connection, init_db


class MemoryService:
    def __init__(self, connection=None):
        self.connection = connection
        init_db()

    def _conn(self) -> sqlite3.Connection:
        if self.connection is not None:
            return self.connection
        return get_connection()

    def add_rule(self, text: str, category: str = "general", source: str = "manual") -> dict[str, Any]:
        rule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO team_rules (id, text, category, source, created_at, usage_count, active) VALUES (?, ?, ?, ?, ?, 0, 1)",
                (rule_id, text, category, source, now),
            )
            conn.commit()
            return self.get_rule(rule_id)
        finally:
            if self.connection is None:
                conn.close()

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM team_rules WHERE id = ?", (rule_id,)).fetchone()
            return dict(row) if row else None
        finally:
            if self.connection is None:
                conn.close()

    def list_rules(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM team_rules ORDER BY created_at DESC").fetchall()
            return [dict(row) for row in rows]
        finally:
            if self.connection is None:
                conn.close()

    def delete_rule(self, rule_id: str) -> None:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM team_rules WHERE id = ?", (rule_id,))
            conn.commit()
        finally:
            if self.connection is None:
                conn.close()

    def get_relevant_rules(self, code: str, limit: int = 5) -> list[dict[str, Any]]:
        if not code:
            return []
        keywords = self._extract_keywords(code)
        if not keywords:
            return []
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM team_rules WHERE active = 1 ORDER BY created_at DESC").fetchall()
            scored = []
            for row in rows:
                rule_text = row["text"].lower()
                score = 0
                for keyword in keywords:
                    if keyword in rule_text:
                        score += 1
                if row["category"] == "architecture" and ("database" in rule_text or "repository" in rule_text or "service" in rule_text):
                    score += 2
                if score > 0:
                    scored.append((score, dict(row)))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [item[1] for item in scored[:limit]]
        finally:
            if self.connection is None:
                conn.close()

    def record_review(self, review_payload: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO reviews (id, filename, language, summary, score, code, findings, memory_used, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review_payload["review_id"],
                    review_payload.get("filename", ""),
                    review_payload.get("language", "python"),
                    review_payload.get("summary", ""),
                    review_payload.get("score", 0),
                    review_payload.get("code", ""),
                    json.dumps(review_payload.get("findings", [])),
                    json.dumps(review_payload.get("memory_used", [])),
                    review_payload.get("created_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            conn.commit()
        finally:
            if self.connection is None:
                conn.close()

    def record_feedback(self, review_id: str, finding_id: str, action: str) -> dict[str, Any]:
        feedback_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        created_rule = None
        try:
            conn.execute(
                "INSERT INTO feedback (id, review_id, finding_id, action, created_at) VALUES (?, ?, ?, ?, ?)",
                (feedback_id, review_id, finding_id, action, now),
            )
            if action == "accepted":
                review_row = conn.execute("SELECT findings FROM reviews WHERE id = ?", (review_id,)).fetchone()
                review_findings = json.loads(review_row["findings"] or "[]") if review_row else []
                finding = next((item for item in review_findings if item.get("id") == finding_id), None)
                if finding:
                    if finding.get("category") == "architecture" and "database" in finding.get("title", "").lower():
                        rule_text = "Database access must be handled through the Repository/Service layer instead of directly inside Controllers."
                        category = "architecture"
                    else:
                        rule_text = finding.get("suggestion", "").strip()
                        category = finding.get("category", "general")
                    if rule_text:
                        existing = conn.execute("SELECT * FROM team_rules WHERE text = ? AND active = 1 LIMIT 1", (rule_text,)).fetchone()
                        if existing:
                            created_rule = dict(existing)
                        else:
                            rule_id = str(uuid.uuid4())
                            conn.execute(
                                "INSERT INTO team_rules (id, text, category, source, created_at, usage_count, active) VALUES (?, ?, ?, ?, ?, 0, 1)",
                                (rule_id, rule_text, category, "accepted_feedback", now),
                            )
                            rule_row = conn.execute("SELECT * FROM team_rules WHERE id = ?", (rule_id,)).fetchone()
                            created_rule = dict(rule_row)
            conn.commit()
        finally:
            if self.connection is None:
                conn.close()
        return {"id": feedback_id, "review_id": review_id, "finding_id": finding_id, "action": action, "created_at": now, "created_rule": created_rule}

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["findings"] = json.loads(result["findings"] or "[]")
            result["memory_used"] = json.loads(result["memory_used"] or "[]")
            return result
        finally:
            if self.connection is None:
                conn.close()

    def list_reviews(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM reviews ORDER BY created_at DESC").fetchall()
            result = []
            for row in rows:
                review = dict(row)
                review["findings"] = json.loads(review["findings"] or "[]")
                review["memory_used"] = json.loads(review["memory_used"] or "[]")
                result.append(review)
            return result
        finally:
            if self.connection is None:
                conn.close()

    def list_memory_items(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT feedback.id, feedback.review_id, feedback.finding_id, feedback.action, feedback.created_at, reviews.findings "
                "FROM feedback LEFT JOIN reviews ON reviews.id = feedback.review_id "
                "ORDER BY feedback.created_at DESC"
            ).fetchall()
            items = []
            for row in rows:
                findings = json.loads(row["findings"] or "[]") if row["findings"] else []
                finding = next((item for item in findings if item.get("id") == row["finding_id"]), {})
                items.append({
                    "id": row["id"],
                    "review_id": row["review_id"],
                    "action": row["action"],
                    "title": finding.get("title", "Review feedback"),
                    "text": finding.get("suggestion", finding.get("description", "")),
                    "created_at": row["created_at"],
                })
            return items
        finally:
            if self.connection is None:
                conn.close()

    def get_dashboard_stats(self) -> dict[str, Any]:
        reviews = self.list_reviews()
        rules = self.list_rules()
        issues_found = sum(
            1 for review in reviews for finding in review["findings"]
            if finding.get("severity", "suggestion") != "suggestion"
        )
        issue_counts: dict[str, int] = {}
        for review in reviews:
            for finding in review["findings"]:
                if finding.get("severity", "suggestion") == "suggestion":
                    continue
                title = finding.get("title", "Review issue")
                issue_counts[title] = issue_counts.get(title, 0) + 1
        conn = self._conn()
        try:
            accepted_feedback = conn.execute("SELECT COUNT(*) FROM feedback WHERE action = 'accepted'").fetchone()[0]
        finally:
            if self.connection is None:
                conn.close()
        most_common_issue = max(issue_counts, key=issue_counts.get) if issue_counts else None
        return {
            "total_reviews": len(reviews),
            "issues_found": issues_found,
            "team_rules": len(rules),
            "memory_items": len(rules) + accepted_feedback,
            "memory_influenced_reviews": sum(1 for review in reviews if review["memory_used"]),
            "most_common_issue": most_common_issue,
            "recent_reviews": reviews[:5],
        }

    def get_similar_reviews(self, code: str, limit: int = 5) -> list[dict[str, Any]]:
        if not code:
            return []
        keywords = self._extract_keywords(code)
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM reviews ORDER BY created_at DESC").fetchall()
            scored = []
            for row in rows:
                review_text = (row["summary"] + " " + row["code"] + " " + json.dumps(row["findings"])).lower()
                score = sum(1 for keyword in keywords if keyword in review_text)
                if score > 0:
                    scored.append((score, dict(row)))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [self._normalize_review(item[1]) for item in scored[:limit]]
        finally:
            if self.connection is None:
                conn.close()

    def reset_demo_data(self) -> None:
        conn = self._conn()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS team_rules (id TEXT PRIMARY KEY, text TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL, usage_count INTEGER DEFAULT 0, active INTEGER DEFAULT 1)")
            conn.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, filename TEXT, language TEXT, summary TEXT, score INTEGER, code TEXT, findings TEXT, memory_used TEXT, created_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, review_id TEXT NOT NULL, finding_id TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("DELETE FROM team_rules")
            conn.execute("DELETE FROM reviews")
            conn.execute("DELETE FROM feedback")
            conn.commit()
        finally:
            if self.connection is None:
                conn.close()

    def _normalize_review(self, row: dict[str, Any]) -> dict[str, Any]:
        row["findings"] = json.loads(row["findings"] or "[]")
        row["memory_used"] = json.loads(row["memory_used"] or "[]")
        return row

    def _extract_keywords(self, code: str) -> list[str]:
        text = code.lower()
        tokens = []
        for fragment in ["db.query", "database", "repository", "service", "controller", "query", "auth", "validation", "duplicate", "type hints"]:
            if fragment in text:
                tokens.append(fragment)
        return tokens
