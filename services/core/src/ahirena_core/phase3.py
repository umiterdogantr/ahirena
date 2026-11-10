"""Aşama 3 HTTP uçları: çalışma alanı, kullanıcı hafızası ve belge araması."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .config import Settings
from .knowledge import (
    KnowledgeError,
    add_memory,
    create_workspace,
    delete_document,
    delete_memory,
    import_document,
    list_documents,
    list_index_jobs,
    list_memory,
    list_workspaces,
    retry_failed_jobs,
    search_documents,
    search_memory,
    supersede_memory,
    update_memory,
)
from .storage import StorageError


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MemoryBody(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=4000)
    source_ref: str = Field(min_length=1, max_length=500)


class MemoryUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    source_ref: str = Field(min_length=1, max_length=500)


class ImportDoc(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=500)


def register_phase3(app: FastAPI, settings: Settings) -> None:
    del settings

    def db():
        return app.state.store.db

    def guard(work):
        try:
            return work()
        except (KnowledgeError, StorageError) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/workspaces")
    async def get_workspaces() -> list[dict]:
        return list_workspaces(db())

    @app.post("/api/workspaces")
    async def post_workspace(body: WorkspaceBody) -> dict:
        return guard(lambda: create_workspace(db(), body.name))

    @app.get("/api/memory")
    async def get_memory(workspace_id: str = Query(min_length=1)) -> list[dict]:
        return guard(lambda: list_memory(db(), workspace_id))

    @app.post("/api/memory")
    async def post_memory(body: MemoryBody) -> dict:
        return guard(lambda: add_memory(db(), body.workspace_id, body.body, body.source_ref))

    @app.patch("/api/memory/{memory_id}")
    async def patch_memory(memory_id: str, body: MemoryUpdate) -> dict:
        return guard(lambda: update_memory(db(), memory_id, body.body, body.source_ref))

    @app.post("/api/memory/{memory_id}/supersede")
    async def post_supersede(memory_id: str) -> dict:
        return guard(lambda: supersede_memory(db(), memory_id))

    @app.delete("/api/memory/{memory_id}")
    async def remove_memory(memory_id: str) -> dict:
        return guard(lambda: delete_memory(db(), memory_id))

    @app.get("/api/memory/search")
    async def find_memory(workspace_id: str = Query(min_length=1), q: str = Query(min_length=1)) -> dict:
        return guard(lambda: search_memory(db(), workspace_id, q))

    @app.get("/api/documents")
    async def get_documents(workspace_id: str = Query(min_length=1)) -> list[dict]:
        return guard(lambda: list_documents(db(), workspace_id))

    @app.post("/api/documents/import")
    async def post_document(body: ImportDoc) -> dict:
        return guard(lambda: import_document(db(), body.workspace_id, body.path))

    @app.delete("/api/documents/{document_id}")
    async def remove_document(document_id: str) -> dict:
        return guard(lambda: delete_document(db(), document_id))

    @app.get("/api/documents/search")
    async def find_documents(workspace_id: str = Query(min_length=1), q: str = Query(min_length=1)) -> dict:
        return guard(lambda: search_documents(db(), workspace_id, q))

    @app.get("/api/documents/jobs")
    async def get_document_jobs(workspace_id: str = Query(min_length=1)) -> list[dict]:
        return guard(lambda: list_index_jobs(db(), workspace_id))

    @app.post("/api/documents/jobs/retry")
    async def retry_document_jobs(workspace_id: str = Query(min_length=1)) -> dict:
        return guard(lambda: retry_failed_jobs(db(), workspace_id))
