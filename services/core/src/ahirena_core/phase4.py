"""Aşama 4 HTTP uçları: görev, onay, uzlaştırma ve ağ politikası."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .config import Settings
from .filesafe import FileRejected
from .netpolicy import NetRejected, tor_listening
from .tasks import TaskEngine, TaskError


class TaskBody(BaseModel):
    title: str = Field(default="", max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    grant: dict = Field(default_factory=dict)
    route: str = "direct"
    workspace_id: str = "genel"
    schedule_at: str | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=86400 * 30)
    timezone: str = "Europe/Istanbul"
    missed_policy: str = "skip"


class ApproveBody(BaseModel):
    approval_id: str = Field(min_length=1, max_length=80)


class ReconcileBody(BaseModel):
    decision: str = Field(min_length=1, max_length=20)


def _network_cfg(data_dir: Path) -> dict:
    path = data_dir / "config.json"
    if not path.exists():
        return {"tor_socks": "127.0.0.1:9050", "offline": False}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    net = raw.get("network") or {}
    return {
        "tor_socks": net.get("tor_socks") or "127.0.0.1:9050",
        "offline": bool(net.get("offline")),
    }


def _save_network_cfg(data_dir: Path, *, offline: bool, tor_socks: str) -> dict:
    path = data_dir / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    socks = (tor_socks or "").strip() or "127.0.0.1:9050"
    if ":" not in socks:
        raise TaskError("Tor SOCKS adresi host:port olmalı.")
    raw["network"] = {"offline": bool(offline), "tor_socks": socks}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return _network_cfg(data_dir)


class NetworkBody(BaseModel):
    offline: bool = False
    tor_socks: str = Field(default="127.0.0.1:9050", max_length=120)


def register_phase4(app: FastAPI, settings: Settings) -> None:
    def engine() -> TaskEngine:
        return app.state.tasks

    def guard(work):
        try:
            return work()
        except TaskError as e:
            raise HTTPException(400, str(e)) from e
        except (FileRejected, NetRejected) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/tasks")
    async def list_tasks(state: str | None = Query(default=None, max_length=40)) -> list[dict]:
        return engine().list(state=state)

    @app.post("/api/tasks")
    async def create_task(body: TaskBody) -> dict:
        return guard(lambda: engine().create(body.model_dump()))

    @app.post("/api/tasks/purge-terminal")
    async def purge_terminal_tasks() -> dict:
        return engine().purge_terminal()

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        return guard(lambda: engine().get(task_id))

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str) -> dict:
        return guard(lambda: engine().delete(task_id))

    @app.post("/api/tasks/{task_id}/run")
    async def run_task(task_id: str) -> dict:
        return guard(lambda: engine().run(task_id))

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str) -> dict:
        return guard(lambda: engine().cancel(task_id))

    @app.post("/api/tasks/{task_id}/approve")
    async def approve_task(task_id: str, body: ApproveBody) -> dict:
        return guard(lambda: engine().approve(task_id, body.approval_id))

    @app.post("/api/tasks/{task_id}/deny")
    async def deny_task(task_id: str, body: ApproveBody) -> dict:
        return guard(lambda: engine().deny(task_id, body.approval_id))

    @app.post("/api/tasks/{task_id}/reconcile")
    async def reconcile_task(task_id: str, body: ReconcileBody) -> dict:
        return guard(lambda: engine().reconcile(task_id, body.decision))

    # branch/replay Aşama 5'te register_phase5 ile eklenir.

    def _network_view() -> dict:
        cfg = _network_cfg(settings.data_dir)
        socks = cfg["tor_socks"]
        return {
            "offline": cfg["offline"],
            "tor_socks": socks,
            "tor_listening": tor_listening(socks),
            "worker": "cekirdek_acikken",
            "os_autostart": False,
            "browser_sessions": "kapalı",
            "note": "Ağ politikası kapalı ile işletim sistemi çıkış engeli ayrıdır. Tor yoksa web.tor başarısız olur, doğrudan çıkılmaz.",
        }

    @app.get("/api/network")
    async def get_network() -> dict:
        return _network_view()

    @app.put("/api/network")
    async def put_network(body: NetworkBody) -> dict:
        try:
            cfg = _save_network_cfg(settings.data_dir, offline=body.offline, tor_socks=body.tor_socks)
        except TaskError as e:
            raise HTTPException(400, str(e)) from e
        engine = app.state.tasks
        engine.offline = cfg["offline"]
        engine.tor_socks = cfg["tor_socks"]
        return _network_view()

    @app.post("/api/network/tor-probe")
    async def probe_tor() -> dict:
        cfg = _network_cfg(settings.data_dir)
        socks = cfg["tor_socks"]
        listening = tor_listening(socks)
        return {
            "tor_socks": socks,
            "tor_listening": listening,
            "external_fetch": False,
            "direct_fallback": False,
            "ok": listening,
            "note": (
                "Yalnızca yerel SOCKS bağlantısı denendi; dış siteye istek atılmadı. "
                "Dinlemiyorsa web.tor görevi başarısız olur, doğrudan internete düşülmez."
                if listening
                else "Tor SOCKS dinlemiyor. web.tor görevi reddedilir; doğrudan çıkış yapılmaz."
            ),
        }


async def task_worker(app: FastAPI) -> None:
    try:
        while True:
            try:
                app.state.tasks.tick()
            except Exception:
                pass
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        return
