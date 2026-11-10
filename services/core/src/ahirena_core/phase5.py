"""Aşama 5: medya durumu, görev dalı, çevrimdışı oynatma, yetenek taslağı."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .media import media_status
from .skilldraft import SkillError, discard_candidate, draft_skill, list_candidates
from .tasks import TaskError


class BranchBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    route: str | None = None
    params: dict | None = None
    grant: dict | None = None


class DraftBody(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)
    tools: list[str] | None = None


def register_phase5(app: FastAPI, settings: Settings) -> None:
    def engine():
        return app.state.tasks

    def guard(work):
        try:
            return work()
        except (TaskError, SkillError) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/media")
    async def get_media() -> dict:
        vision: list[str] = []
        try:
            models = await app.state.registry.get("ollama").list_models()
            vision = [m.model_id for m in models if "vision" in (m.capabilities or [])]
        except Exception:
            vision = []
        return media_status(vision_models=vision)

    @app.post("/api/tasks/{task_id}/branch")
    async def branch_task(task_id: str, body: BranchBody) -> dict:
        return guard(lambda: engine().branch(task_id, body.model_dump(exclude_none=True)))

    @app.post("/api/tasks/{task_id}/replay")
    async def replay_task(task_id: str) -> dict:
        return guard(lambda: engine().replay(task_id))

    @app.get("/api/skills/candidates")
    async def candidates() -> list[dict]:
        return list_candidates(app.state.store.db)

    @app.post("/api/skills/draft")
    async def draft(body: DraftBody) -> dict:
        return guard(lambda: draft_skill(app.state.store.db, settings.data_dir, body.prompt, body.tools))

    @app.post("/api/skills/candidates/{candidate_id}/discard")
    async def discard(candidate_id: str) -> dict:
        return guard(lambda: discard_candidate(app.state.store.db, candidate_id))
