@echo off
rem Yerel modellerin bu cihazdaki hiz ve bellek olcumu.
rem Kullanim: scripts\olcum.cmd            (yuklu tum modeller)
rem           scripts\olcum.cmd qwen3.5:4b-q4_K_M gemma4:e2b-it-qat
setlocal
cd /d "%~dp0.."
where uv >nul 2>nul || (echo uv bulunamadi. Kurulum: winget install astral-sh.uv & exit /b 1)
uv run --project services\core python evals\bench\run_bench.py %*
