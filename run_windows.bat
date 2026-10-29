@echo off
setlocal

echo ========================================
echo   ClipClean - Video Processing Tool
echo ========================================
echo.

cd /d "%~dp0"

:: ── Check for local FFmpeg ──────────────────────────────
if exist "%~dp0..\ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%~dp0..\ffmpeg\bin;%PATH%"
) else if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%~dp0ffmpeg\bin;%PATH%"
)

:: ── Check Python ─────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo.
    echo   Download Python from:
    echo     https://www.python.org/downloads/
    echo.
    echo   During installation, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
echo [OK] Python found.

:: ── Check FFmpeg ─────────────────────────────────────────
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FFmpeg is NOT found on PATH.
    echo.
    echo   ClipClean requires FFmpeg for video processing.
    echo.
    echo   How to install FFmpeg on Windows:
    echo     1. Go to https://www.gyan.dev/ffmpeg/builds/
    echo     2. Download "ffmpeg-release-essentials.zip"
    echo     3. Extract the ZIP to a folder, e.g. C:\ffmpeg
    echo     4. Add C:\ffmpeg\bin to your system PATH:
    echo        - Press Win+R, type "sysdm.cpl", press Enter
    echo        - Click "Advanced" tab ^> "Environment Variables"
    echo        - Under "System variables", select "Path", click "Edit"
    echo        - Click "New" and type:  C:\ffmpeg\bin
    echo        - Click OK on all dialogs
    echo     5. Close and reopen this terminal
    echo     6. Verify: type "ffmpeg -version" and press Enter
    echo.
    echo   The app will start but CANNOT process videos without FFmpeg.
    echo.
) else (
    echo [OK] FFmpeg found.
)

:: ── Check FFprobe ────────────────────────────────────────
ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FFprobe is NOT found. It is bundled with FFmpeg.
) else (
    echo [OK] FFprobe found.
)

:: ── Virtual environment ──────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: ── Install dependencies ─────────────────────────────────
echo.
echo Installing Python dependencies...
.venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo   Try running:  .venv\Scripts\pip.exe install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

:: ── Start server ─────────────────────────────────────────
echo.
echo ========================================
echo   Starting ClipClean server...
echo ========================================
echo.
echo   Open your browser and go to:
echo.
echo     http://127.0.0.1:8000
echo.
echo   Press Ctrl+C to stop the server.
echo ========================================
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

endlocal
