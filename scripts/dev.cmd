@echo off
rem Gelistirme modu: arayuz canli yenilenir, cekirdek "uv run" ile calisir.
setlocal
cd /d "%~dp0..\apps\desktop"
if not exist node_modules call npm ci || exit /b 1
call npm run tauri dev
