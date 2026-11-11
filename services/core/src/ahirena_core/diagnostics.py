"""Dürüst durum özeti: sahte yeşil ışık yok."""

from __future__ import annotations

import json
from pathlib import Path

from .artifacts import register_file
from .db import Database, utcnow
from .media import media_status
from .netpolicy import tor_listening
from .phase4 import _network_cfg
from .storage import disk_status, require_space
from .training import capability


class DiagnosticsError(ValueError):
    pass


def build_diagnostics(data_dir: Path, *, active_runs: list[str], task_counts: dict) -> dict:
    net = _network_cfg(data_dir)
    media = media_status(vision_models=[])
    train = capability(data_dir)
    disk = disk_status(data_dir)
    return {
        "local_first": True,
        "remote_providers": False,
        "ollama_cloud_policy": "managed_instances_use_OLLAMA_NO_CLOUD=1",
        "network": {
            "offline": net["offline"],
            "tor_socks": net["tor_socks"],
            "tor_listening": tor_listening(net["tor_socks"]),
            "os_firewall": False,
            "note": "Ağ politikası OS duvarı değildir.",
        },
        "disk": disk,
        "media": {
            "ocr": media["ocr"]["status"],
            "speech_input": media["speech_input"]["status"],
            "speech_output": media["speech_output"]["status"],
            "screen_watch": media["screen_watch"]["status"],
        },
        "training": {"status": train["status"], "runner": train["runner"]},
        "tasks": {
            "worker": "cekirdek_acikken",
            "os_autostart": False,
            **task_counts,
        },
        "active_runs": active_runs,
        "scripts": "kapalı",
        "browser_sessions": "kapalı",
    }


def save_diagnostics(
    db: Database,
    data_dir: Path,
    *,
    active_runs: list[str],
    task_counts: dict,
) -> dict:
    """Tanılama özetini reports altına yazar ve çıktı kaydı oluşturur."""
    require_space(data_dir)
    payload = build_diagnostics(data_dir, active_runs=active_runs, task_counts=task_counts)
    stamp = utcnow().replace(":", "").replace("+", "z")[:20]
    reports = data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"diagnostics-{stamp}.json"
    if path.exists():
        raise DiagnosticsError("Tanılama dosyası zaten var.")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = register_file(
        db,
        path,
        kind="export",
        title=f"Tanılama {stamp}",
        media_type="application/json",
    )
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "artifact_id": artifact["id"],
        "diagnostics": payload,
    }
