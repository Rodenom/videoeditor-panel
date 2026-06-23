@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════╗
echo ║  Video Editor — Установка (Windows)  ║
echo ╚══════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ► Python не найден. Открываем страницу загрузки...
    echo   Скачай Python 3.11 и установи, потом запусти этот файл снова.
    start https://www.python.org/downloads/
    pause
    exit
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo ✓ Python %%v установлен
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo ► ffmpeg не найден. Устанавливаем через winget...
    winget install --id Gyan.FFmpeg -e --silent
    if %errorlevel% neq 0 (
        echo   Не удалось автоустановить ffmpeg.
        echo   Скачай вручную: https://ffmpeg.org/download.html
        echo   Распакуй и добавь bin/ в PATH
        pause
    )
) else (
    echo ✓ ffmpeg уже установлен
)

:: Install Python dependencies
echo ► Устанавливаем Python библиотеки...
pip install --quiet google-auth google-auth-oauthlib google-api-python-client anthropic httplib2 PySocks

echo.
echo ╔══════════════════════════════════════╗
echo ║       Установка завершена!           ║
echo ╚══════════════════════════════════════╝
echo.
echo ► Запускаем панель...
echo   Открой браузер и зайди на http://localhost:7777
echo.

cd /d "%~dp0"
python app.py
pause
