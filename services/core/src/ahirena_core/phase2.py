"""Aşama 2 HTTP uçları: yetenek, izin, MCP ve salt okunur SQL."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .filesafe import FileRejected
from .mcp_client import McpError, McpRegistry
from .skills import SkillError, SkillRegistry
from .sqlexec import SqlConfig, SqlRejected, load_sql_config, probe, query, save_sql_config


class ImportBody(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class EnableBody(BaseModel):
    grants: list[dict] = Field(default_factory=list)


class CallBody(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)


class RollbackBody(BaseModel):
    content_hash: str = Field(min_length=8, max_length=128)


class McpBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    command: str = Field(min_length=1, max_length=500)
    args: list[str] = Field(default_factory=list)


class McpGrantBody(BaseModel):
    tool: str = Field(min_length=1, max_length=80)


class SqlBody(BaseModel):
    enabled: bool
    server: str = Field(default="", max_length=200)
    database: str = Field(default="", max_length=128)
    driver: str = Field(default="", max_length=120)


def register_phase2(app: FastAPI, settings: Settings) -> None:
    def skills() -> SkillRegistry:
        return SkillRegistry(app.state.store.db, settings.data_dir)

    def mcp() -> McpRegistry:
        return McpRegistry(app.state.store.db)

    def run_sql(sql: str) -> dict:
        try:
            return query(load_sql_config(settings.data_dir), sql)
        except SqlRejected as e:
            raise SkillError(str(e)) from e

    @app.get("/api/skills")
    async def list_skills() -> list[dict]:
        return skills().list()

    @app.post("/api/skills/import")
    async def import_skill(body: ImportBody) -> dict:
        try:
            return skills().import_dir(body.path)
        except SkillError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/skills/{skill_id}/enable")
    async def enable_skill(skill_id: str, body: EnableBody) -> dict:
        try:
            return skills().set_enabled(skill_id, True, body.grants)
        except (SkillError, FileRejected) as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/skills/{skill_id}/disable")
    async def disable_skill(skill_id: str) -> dict:
        try:
            return skills().set_enabled(skill_id, False)
        except SkillError as e:
            raise HTTPException(404, str(e)) from e

    @app.delete("/api/skills/{skill_id}")
    async def delete_skill(skill_id: str) -> dict:
        try:
            return skills().uninstall(skill_id)
        except SkillError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/skills/{skill_id}/call")
    async def call_skill(skill_id: str, body: CallBody) -> dict:
        try:
            return skills().call(skill_id, body.tool, body.arguments, run_sql)
        except SkillError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/skills/{skill_id}/versions")
    async def skill_versions(skill_id: str) -> dict:
        try:
            return skills().list_versions(skill_id)
        except SkillError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/skills/{skill_id}/rollback")
    async def skill_rollback(skill_id: str, body: RollbackBody) -> dict:
        try:
            return skills().rollback(skill_id, body.content_hash)
        except SkillError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/mcp")
    async def list_mcp() -> list[dict]:
        return mcp().list()

    @app.post("/api/mcp")
    async def add_mcp(body: McpBody) -> dict:
        try:
            return mcp().add(body.name, body.command, body.args)
        except McpError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/api/mcp/{server_id}")
    async def delete_mcp(server_id: str) -> dict:
        try:
            return mcp().remove(server_id)
        except McpError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/mcp/{server_id}/refresh")
    async def refresh_mcp(server_id: str) -> dict:
        try:
            return mcp().refresh(server_id)
        except McpError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/mcp/{server_id}/grant")
    async def grant_mcp(server_id: str, body: McpGrantBody) -> dict:
        try:
            return mcp().grant(server_id, body.tool)
        except McpError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/mcp/{server_id}/revoke")
    async def revoke_mcp(server_id: str, body: McpGrantBody) -> dict:
        try:
            return mcp().revoke(server_id, body.tool)
        except McpError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/mcp/{server_id}/call")
    async def call_mcp(server_id: str, body: CallBody) -> dict:
        try:
            return mcp().call(server_id, body.tool, body.arguments)
        except McpError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/sql")
    async def get_sql() -> dict:
        cfg = load_sql_config(settings.data_dir)
        return {"enabled": cfg.enabled, "server": cfg.server, "database": cfg.database, "driver": cfg.driver, "auth": "windows", "writes": "kapalı"}

    @app.put("/api/sql")
    async def put_sql(body: SqlBody) -> dict:
        try:
            cfg = SqlConfig(enabled=body.enabled, server=body.server.strip(), database=body.database.strip(), driver=body.driver.strip())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        save_sql_config(settings.data_dir, cfg)
        return {"enabled": cfg.enabled, "server": cfg.server, "database": cfg.database, "driver": cfg.driver, "auth": "windows", "writes": "kapalı"}

    @app.post("/api/sql/probe")
    async def probe_sql() -> dict:
        try:
            return {"ok": True, "result": probe(load_sql_config(settings.data_dir))}
        except SqlRejected as e:
            return {"ok": False, "error": str(e)}
