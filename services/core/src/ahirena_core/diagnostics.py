"""Dürüst durum özeti: sahte yeşil ışık yok."""

from __future__ import annotations

from pathlib import Path

from .media import media_status
from .netpolicy import tor_listening
from .phase4 import _network_cfg
from .storage import disk_status
from .training import capability


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
