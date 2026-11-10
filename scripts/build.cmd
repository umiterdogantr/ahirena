@echo off
rem Paketli surum: cekirdegi tek .exe yapar, Tauri ile kullanici duzeyinde NSIS kurulum dosyasi uretir.
rem Cikti: <CARGO_TARGET_DIR veya apps\desktop\src-tauri\target>\release\bundle\nsis\Ahirena_*_x64-setup.exe
setlocal
cd /d "%~dp0.."
set ROOT=%CD%
set BIN=%ROOT%\apps\desktop\src-tauri\binaries
set TRIPLE=x86_64-pc-windows-msvc

echo [1/3] Cekirdek paketleniyor (PyInstaller)...
pushd services\core
uv sync --frozen || (popd & exit /b 1)
uv run pyinstaller --noconfirm --clean --onefile --name ahirena-core --distpath build\dist --workpath build\work --specpath build ^
  --paths src --collect-submodules ahirena_core --hidden-import pyodbc packaging\launcher.py || (popd & exit /b 1)
uv run pytest -m packaged -q || (popd & exit /b 1)
popd
if not exist "%BIN%" mkdir "%BIN%"
copy /y services\core\build\dist\ahirena-core.exe "%BIN%\ahirena-core-%TRIPLE%.exe" >nul || exit /b 1

echo [2/3] Arayuz bagimliliklari...
pushd apps\desktop
if not exist node_modules call npm ci || (popd & exit /b 1)

echo [3/3] Masaustu uygulamasi derleniyor...
call npm run tauri build -- --config src-tauri\tauri.bundle.json || (popd & exit /b 1)
popd
set TARGET=%CARGO_TARGET_DIR%
if "%TARGET%"=="" set TARGET=%ROOT%\apps\desktop\src-tauri\target
echo.
echo Kurulum dosyasi:
dir /s /b "%TARGET%\release\bundle\nsis\*.exe"
