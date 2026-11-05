import asyncio
import json
import os

import pytest

from ahirena_core.config import OllamaConfig, default_data_dir, load_ollama_config
from ahirena_core.ollama_runtime import OllamaRuntime, server_env


def test_legacy_data_dir_is_migrated_once(tmp_path, monkeypatch):
    old = tmp_path / "Ahirena"
    (old / "data").mkdir(parents=True)
    (old / "data" / "ahirena.db").write_text("eski", encoding="utf-8")
    (old / "config.json").write_text("{}", encoding="utf-8")
    new = tmp_path / "com.ahirena.desktop"
    new.mkdir()
    (new / "config.json").write_text('{"ollama": {}}', encoding="utf-8")
    (old / "ahirena.exe").write_text("program", encoding="utf-8")
    monkeypatch.delenv("AHIRENA_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_data_dir() == new
    assert (new / "data" / "ahirena.db").read_text(encoding="utf-8") == "eski"
    assert not (old / "data").exists()
    assert (new / "config.json").read_text(encoding="utf-8") == '{"ollama": {}}'
    assert (old / "config.json").exists()
    assert (old / "ahirena.exe").exists()


def test_config_created_with_defaults(tmp_path):
    cfg = load_ollama_config(tmp_path)
    assert cfg == OllamaConfig()
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["ollama"]["host"] == "127.0.0.1:11435"
    assert saved["ollama"]["manage"] is True


def test_config_reads_user_values_with_bom(tmp_path):
    body = {"ollama": {"models_dir": "D:\\m", "backend": "vulkan", "unknown": 1}}
    (tmp_path / "config.json").write_text(json.dumps(body), encoding="utf-8-sig")
    cfg = load_ollama_config(tmp_path)
    assert cfg.models_dir == "D:\\m"
    assert cfg.backend == "vulkan"


def test_invalid_backend_is_rejected(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"ollama": {"backend": "magic"}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_ollama_config(tmp_path)


def test_server_env_forces_local_and_backend():
    env = server_env(OllamaConfig(host="127.0.0.1:1234", models_dir="D:\\m", backend="vulkan"))
    assert env["OLLAMA_HOST"] == "127.0.0.1:1234"
    assert env["OLLAMA_NO_CLOUD"] == "1"
    assert env["OLLAMA_MODELS"] == "D:\\m"
    assert env["CUDA_VISIBLE_DEVICES"] == "-1"
    assert env["OLLAMA_VULKAN"] == "1"
    auto = server_env(OllamaConfig(backend="auto"))
    assert auto.get("CUDA_VISIBLE_DEVICES") == os.environ.get("CUDA_VISIBLE_DEVICES")


def test_managed_refuses_non_loopback(tmp_path):
    rt = OllamaRuntime(OllamaConfig(host="0.0.0.0:9"), tmp_path)
    assert asyncio.run(rt.ensure()) is False
    assert rt.state == "error"
    assert "127.0.0.1" in (rt.error or "")
    assert rt.proc is None


def test_missing_exe_reports_clear_error(tmp_path):
    rt = OllamaRuntime(OllamaConfig(host="127.0.0.1:9", exe=str(tmp_path / "yok.exe")), tmp_path)
    assert asyncio.run(rt.ensure()) is False
    assert "bulunamadı" in (rt.error or "")


def test_unmanaged_unreachable_is_reported(tmp_path):
    rt = OllamaRuntime(OllamaConfig(manage=False, host="127.0.0.1:9"), tmp_path)
    assert asyncio.run(rt.ensure()) is False
    assert rt.state == "unavailable"
    assert rt.info()["pid"] is None
