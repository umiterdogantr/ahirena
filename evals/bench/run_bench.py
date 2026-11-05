"""Yerel modellerin bu cihazdaki ölçümü (KAB 19).

Her model için önce bellek boşaltılır ve ilk soru "soğuk" çalıştırılır; ardından
bütün sorular "sıcak" çalıştırılır. İlk token süresi istemci tarafında ölçülür;
hız, yükleme ve token sayıları Ollama'nın bildirdiği değerlerdir. Yanıtlar
kullanıcı değerlendirmesi için Markdown dosyasına da yazılır. Bu betik model
kalitesine puan vermez; yalnızca deterministik içerik denetimlerini raporlar.

Çalıştırma: scripts\\olcum.cmd  [model ...]
"""

from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ahirena_core.config import Settings
from ahirena_core.ollama_runtime import OllamaRuntime
from ahirena_core.providers import ChatMessage, ChatOptions
from ahirena_core.providers.ollama import OllamaProvider

HERE = Path(__file__).parent
NUM_CTX = 4096


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(out.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def gpu_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        name, driver, total = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
        return {"gpu": name, "driver": driver, "vram_total": total}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {}


async def one(p: OllamaProvider, model: str, prompt: dict, phase: str) -> dict:
    msgs = [ChatMessage("user", prompt["text"])]
    started = time.perf_counter()
    ttft = None
    text = ""
    stats: dict = {}
    error = None
    try:
        async for ev in p.chat_stream(model, msgs, ChatOptions(think=False, context_length=NUM_CTX)):
            if ev.kind in ("content", "thinking") and ttft is None:
                ttft = (time.perf_counter() - started) * 1000
            if ev.kind == "content":
                text += ev.text
            elif ev.kind == "done":
                stats = ev.stats or {}
    except Exception as e:  # ölçüm devam etsin; hata rapora yazılır
        error = f"{e.__class__.__name__}: {e}"
    placement = next((m for m in await p.loaded_models() if m.model_id == model), None)
    expect = prompt.get("expect_any")
    return {
        "model_id": model,
        "phase": phase,
        "prompt_id": prompt["id"],
        "ttft_ms": round(ttft, 1) if ttft is not None else None,
        "tokens_per_s": stats.get("tokens_per_s"),
        "total_ms": stats.get("total_ms"),
        "load_ms": stats.get("load_ms"),
        "prompt_tokens": stats.get("prompt_tokens"),
        "output_tokens": stats.get("output_tokens"),
        "gpu_percent": placement.gpu_percent if placement else None,
        "model_memory_bytes": placement.size_bytes if placement else None,
        "model_ram_bytes": (placement.size_bytes - placement.vram_bytes) if placement else None,
        "model_vram_bytes": placement.vram_bytes if placement else None,
        "gpu_used_mib_after": gpu_used_mib(),
        "check": None if not expect else any(e.lower() in text.lower() for e in expect),
        "response": text,
        "error": error,
    }


async def main(models: list[str]) -> Path:
    prompts = json.loads((HERE / "prompts_tr.json").read_text(encoding="utf-8"))
    settings = Settings.local()
    runtime = OllamaRuntime(settings.ollama, settings.log_dir)
    if not await runtime.ensure():
        raise SystemExit(f"Ollama başlatılamadı: {runtime.error}")
    print(f"Ollama: {runtime.url} ({runtime.state}, arka uç: {settings.ollama.backend})", flush=True)
    p = OllamaProvider(runtime.url)
    try:
        health = await p.health()
        if not health.ok:
            raise SystemExit(f"Ollama çalışmıyor: {health.error}")
        installed = {m.model_id: m for m in await p.list_models()}
        models = models or list(installed)
        missing = [m for m in models if m not in installed]
        if missing:
            raise SystemExit(f"Yüklü olmayan model: {', '.join(missing)}")

        results: list[dict] = []
        for model in models:
            for lm in await p.loaded_models():
                await p.unload(lm.model_id)
            await asyncio.sleep(2)
            idle_gpu = gpu_used_mib()
            print(f"[{model}] soğuk başlangıç (boşta GPU: {idle_gpu} MiB)…", flush=True)
            r = await one(p, model, prompts["prompts"][0], "cold")
            r["gpu_used_mib_idle"] = idle_gpu
            r["digest"] = installed[model].digest
            results.append(r)
            for pr in prompts["prompts"]:
                print(f"[{model}] sıcak: {pr['id']}", flush=True)
                r = await one(p, model, pr, "warm")
                r["digest"] = installed[model].digest
                results.append(r)
            await p.unload(model)

        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "prompts_version": prompts["version"],
            "num_ctx": NUM_CTX,
            "machine": {
                "os": platform.platform(),
                "cpu": platform.processor(),
                "ollama": health.version,
                "ollama_backend": settings.ollama.backend,
                "ollama_state": runtime.state,
                **gpu_info(),
            },
            "results": results,
        }
    finally:
        await p.aclose()
        runtime.stop()

    out_dir = settings.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"bench-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# Ölçüm {stamp}", "", f"Cihaz: {report['machine']}", ""]
    for r in results:
        if r["phase"] != "warm":
            continue
        check = "" if r["check"] is None else (" — denetim: GEÇTİ" if r["check"] else " — denetim: KALDI")
        md += [f"## {r['model_id']} · {r['prompt_id']}{check}", "", r["error"] or r["response"], ""]
    path.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = asyncio.run(main(sys.argv[1:]))
    print(f"Rapor: {out}")
    print(f"Yanıtlar: {out.with_suffix('.md')}")
