import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.review_agent import CodeReviewAgent
from app.analyzers.language_analyzer import SUPPORTED_LANGUAGES
from app.config import ai_configured
from app.database.database import init_db
from app.memory.memory_service import MemoryService

router = APIRouter()
memory_service = MemoryService()
review_agent = CodeReviewAgent(memory_service=memory_service)


class ReviewRequest(BaseModel):
    code: str
    language: str = "python"
    filename: str = "review.py"


class RuleRequest(BaseModel):
    text: str
    category: str = "architecture"
    source: str = "manual"


class FeedbackRequest(BaseModel):
    review_id: str
    finding_id: str
    action: str


@router.on_event("startup")
def startup():
    init_db()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/review")
def review_code(payload: ReviewRequest) -> dict[str, Any]:
    if not payload.code or not payload.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty.")
    if payload.language.lower() not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise HTTPException(status_code=400, detail=f"Unsupported language. Choose one of: {supported}.")
    try:
        result = review_agent.review_code(payload.code, payload.language, payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "review_id": result["review_id"],
        "summary": result["summary"],
        "score": result["score"],
        "findings": result["findings"],
        "memory_used": result["memory_used"],
    }


@router.get("/api/rules")
def list_rules() -> dict[str, Any]:
    rules = memory_service.list_rules()
    return {"rules": rules}


@router.post("/api/rules")
def add_rule(payload: RuleRequest) -> dict[str, Any]:
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Rule text cannot be empty.")
    rule = memory_service.add_rule(payload.text.strip(), payload.category, payload.source)
    return {"rule": rule}


@router.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str) -> dict[str, str]:
    memory_service.delete_rule(rule_id)
    return {"status": "deleted"}


@router.get("/api/reviews")
def list_reviews() -> dict[str, Any]:
    return {"reviews": memory_service.list_reviews()}


@router.get("/api/memory")
def list_memory() -> dict[str, Any]:
    return {"rules": memory_service.list_rules(), "items": memory_service.list_memory_items()}


@router.get("/api/stats")
def dashboard_stats() -> dict[str, Any]:
    return {
        **memory_service.get_dashboard_stats(),
        "ai_provider": "Azure OpenAI" if ai_configured() else "Deterministic static checks",
    }


@router.get("/api/reviews/{review_id}")
def get_review(review_id: str) -> dict[str, Any]:
    review = memory_service.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found.")
    return review


@router.post("/api/feedback")
def submit_feedback(payload: FeedbackRequest) -> dict[str, Any]:
    if payload.action not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Action must be accepted or rejected.")
    feedback = memory_service.record_feedback(payload.review_id, payload.finding_id, payload.action)
    return {"feedback": feedback}


@router.post("/api/demo/reset")
def reset_demo() -> dict[str, str]:
    memory_service.reset_demo_data()
    return {"status": "demo_reset"}
