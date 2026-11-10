"""Aşama 6: eğitim kaydı ve düzeltme adayları. Çalıştırıcı yoksa iş başlamaz."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .feedback import ISSUE_TYPES, FeedbackError, create_feedback, list_feedback, set_feedback_status
from .training import TrainingError, capability, create_run, list_adapters, list_runs


class TrainBody(BaseModel):
    base_model: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2000)
    data_version: str = Field(default="tanımsız", max_length=200)
    method: str = "lora"
    why_not_rag: str = Field(default="", max_length=2000)
    holdout: str = Field(default="", max_length=2000)
    start: bool = False


class FeedbackBody(BaseModel):
    issue_type: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=4000)
    suggested_fix: str = Field(default="", max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=80)
    message_id: str | None = Field(default=None, max_length=80)


class FeedbackStatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=20)


def register_phase6(app: FastAPI, settings: Settings) -> None:
    def guard(work):
        try:
            return work()
        except (TrainingError, FeedbackError) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/training")
    async def get_training() -> dict:
        return {
            "capability": capability(settings.data_dir),
            "runs": list_runs(app.state.store.db),
            "adapters": list_adapters(app.state.store.db),
            "feedback": list_feedback(app.state.store.db),
            "issue_types": ISSUE_TYPES,
        }

    @app.post("/api/training/runs")
    async def post_run(body: TrainBody) -> dict:
        return guard(lambda: create_run(app.state.store.db, body.model_dump()))

    @app.get("/api/feedback")
    async def get_feedback_list() -> dict:
        return {"items": list_feedback(app.state.store.db), "issue_types": ISSUE_TYPES}

    @app.post("/api/feedback")
    async def post_feedback(body: FeedbackBody) -> dict:
        return guard(lambda: create_feedback(app.state.store.db, body.model_dump()))

    @app.patch("/api/feedback/{feedback_id}")
    async def patch_feedback(feedback_id: str, body: FeedbackStatusBody) -> dict:
        return guard(lambda: set_feedback_status(app.state.store.db, feedback_id, body.status))
