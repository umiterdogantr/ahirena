@echo off
rem Yazilim sozlesme testleri. Gercek model testi icin: scripts\test.cmd ollama
setlocal
cd /d "%~dp0.."
if /i "%~1"=="ollama" (
  pushd services\core && uv run pytest -m ollama -s & popd
  exit /b
)
pushd services\core && uv run pytest || (popd & exit /b 1)
popd
pushd apps\desktop && call npm run typecheck || (popd & exit /b 1)
popd
pushd apps\desktop\src-tauri && cargo test || (popd & exit /b 1)
popd
echo Tum testler gecti.
