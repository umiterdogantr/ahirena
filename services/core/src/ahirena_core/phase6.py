"""Aşama 6: eğitim kaydı, değerlendirme, kabul matrisi, adaptör kaydı, düzeltme adayları.

LoRA çalıştırıcı yoksa eğitim başlamaz; holdout ve kabul matrisi aşamayı kapatır.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .acceptance import AcceptanceError, list_reports, run_matrix
from .config import Settings
from .evaluation import (
    EvaluationError,
    create_set,
    list_runs as list_eval_runs,
    list_sets,
    run_evaluation,
)
from .feedback import (
    ISSUE_TYPES,
    FeedbackError,
    create_feedback,
    export_feedback,
    feedback_to_skill_draft,
    list_feedback,
    set_feedback_status,
)
from .storage import StorageError
from .training import (
    TrainingError,
    activate_adapter,
    capability,
    create_run,
    list_adapters,
    list_runs,
    phase6_status,
    register_adapter,
    rollback_adapter,
)


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


class EvalSetBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data_version: str = Field(default="v1", max_length=80)
    items: list[dict[str, Any]] = Field(min_length=1, max_length=40)


class EvalRunBody(BaseModel):
    set_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=200)
    provider_id: str = Field(default="ollama", max_length=100)
    candidate_id: str | None = Field(default=None, max_length=200)


class AdapterBody(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    base_model: str = Field(min_length=1, max_length=200)
    training_id: str | None = Field(default=None, max_length=80)


def register_phase6(app: FastAPI, settings: Settings) -> None:
    def guard(work):
        try:
            return work()
        except (TrainingError, FeedbackError, StorageError, EvaluationError, AcceptanceError) as e:
            raise HTTPException(400, str(e)) from e

    def provider(provider_id: str):
        try:
            return app.state.registry.get(provider_id)
        except Exception as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/training")
    async def get_training() -> dict:
        return {
            "capability": capability(settings.data_dir),
            "runs": list_runs(app.state.store.db),
            "adapters": list_adapters(app.state.store.db),
            "feedback": list_feedback(app.state.store.db),
            "issue_types": ISSUE_TYPES,
            "evaluation_sets": list_sets(app.state.store.db),
            "evaluation_runs": list_eval_runs(app.state.store.db),
            "acceptance_reports": list_reports(app.state.store.db),
            "phase6": phase6_status(settings.data_dir, app.state.store.db),
        }

    @app.post("/api/training/runs")
    async def post_run(body: TrainBody) -> dict:
        return guard(lambda: create_run(app.state.store.db, body.model_dump()))

    @app.post("/api/training/adapters")
    async def post_adapter(body: AdapterBody) -> dict:
        return guard(
            lambda: register_adapter(
                app.state.store.db,
                settings.data_dir,
                path=body.path,
                base_model=body.base_model,
                training_id=body.training_id,
            )
        )

    @app.post("/api/training/adapters/{adapter_id}/activate")
    async def post_activate(adapter_id: str) -> dict:
        return guard(lambda: activate_adapter(app.state.store.db, adapter_id))

    @app.post("/api/training/adapters/{adapter_id}/rollback")
    async def post_rollback(adapter_id: str) -> dict:
        return guard(lambda: rollback_adapter(app.state.store.db, adapter_id))

    @app.post("/api/evaluation/sets")
    async def post_eval_set(body: EvalSetBody) -> dict:
        return guard(
            lambda: create_set(
                app.state.store.db,
                body.name,
                body.items,
                data_version=body.data_version,
            )
        )

    @app.get("/api/evaluation/sets")
    async def get_eval_sets() -> dict:
        return {"items": list_sets(app.state.store.db)}

    @app.get("/api/evaluation/runs")
    async def get_eval_runs() -> dict:
        return {"items": list_eval_runs(app.state.store.db)}

    @app.post("/api/evaluation/runs")
    async def post_eval_run(body: EvalRunBody) -> dict:
        p = provider(body.provider_id)
        try:
            return await run_evaluation(
                app.state.store.db,
                p,
                set_id=body.set_id,
                model_id=body.model_id,
                candidate_id=body.candidate_id,
            )
        except EvaluationError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/acceptance/run")
    async def post_acceptance() -> dict:
        counts = {"queued": 0, "waiting_approval": 0, "needs_reconciliation": 0}
        try:
            from .tasks import TaskEngine

            for t in TaskEngine(app.state.store.db).list():
                st = t.get("state")
                if st in counts:
                    counts[st] += 1
        except Exception:
            pass
        active = []
        try:
            active = app.state.runs.active_ids()
        except Exception:
            active = []
        return guard(
            lambda: run_matrix(
                app.state.store.db,
                settings.data_dir,
                active_runs=active,
                task_counts=counts,
            )
        )

    @app.get("/api/acceptance/reports")
    async def get_acceptance() -> dict:
        return {"items": list_reports(app.state.store.db)}

    @app.get("/api/feedback")
    async def get_feedback_list(status: str | None = Query(default=None, max_length=20)) -> dict:
        items = list_feedback(app.state.store.db)
        if status:
            items = [i for i in items if i["status"] == status]
        return {"items": items, "issue_types": ISSUE_TYPES, "status_filter": status}

    @app.post("/api/feedback")
    async def post_feedback(body: FeedbackBody) -> dict:
        return guard(lambda: create_feedback(app.state.store.db, body.model_dump()))

    @app.post("/api/feedback/export")
    async def post_feedback_export(status: str | None = Query(default=None, max_length=20)) -> dict:
        return guard(lambda: export_feedback(app.state.store.db, settings.data_dir, status=status))

    @app.patch("/api/feedback/{feedback_id}")
    async def patch_feedback(feedback_id: str, body: FeedbackStatusBody) -> dict:
        return guard(lambda: set_feedback_status(app.state.store.db, feedback_id, body.status))

    @app.post("/api/feedback/{feedback_id}/skill-draft")
    async def post_feedback_skill_draft(feedback_id: str) -> dict:
        return guard(lambda: feedback_to_skill_draft(app.state.store.db, settings.data_dir, feedback_id))
