@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    echo [SETUP] uv belum terpasang. Memasang otomatis...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Gagal memasang uv. Tutup jendela ini, buka ulang, lalu coba lagi.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [SETUP] Berkas .env sudah dibuat.
    echo [SETUP] Isi GEMINI_API_KEY di dalamnya, lalu jalankan run.bat lagi.
    echo [SETUP] Ambil key gratis di https://aistudio.google.com/apikey
    notepad ".env"
    pause
    exit /b 1
)

echo [SETUP] Menyiapkan dependency...
uv sync --quiet
if errorlevel 1 (
    echo [ERROR] Gagal menyiapkan dependency.
    pause
    exit /b 1
)

uv run python run.py
if errorlevel 1 (
    echo.
    echo [ERROR] Aplikasi berhenti dengan error. Baca pesan di atas.
    pause
)
endlocal
