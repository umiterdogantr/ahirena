@echo off
rem Ollama komutlarini Ahirena'nin yonettigi ornege karsi calistirir.
rem Ayarlar: %LOCALAPPDATA%\com.ahirena.desktop\config.json (model klasoru, port, arka uc)
rem Ornek:   scripts\ollama.cmd pull gemma4:e2b-it-qat
rem          scripts\ollama.cmd list
setlocal
cd /d "%~dp0.."
where uv >nul 2>nul || (echo uv bulunamadi. Kurulum: winget install astral-sh.uv & exit /b 1)
uv run --project services\core python -m ahirena_core.ollama_runtime %*
