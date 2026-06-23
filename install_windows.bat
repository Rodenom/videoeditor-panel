@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════╗
echo ║  Video Editor — Установка (Windows)  ║
echo ╚══════════════════════════════════════╝
echo.

cd /d "%~dp0"

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
) else (
    echo ✓ ffmpeg уже установлен
)

:: Install Python dependencies
echo ► Устанавливаем Python библиотеки...
pip install --quiet google-auth google-auth-oauthlib google-api-python-client anthropic httplib2 PySocks

:: Auto-update app.py from GitHub
echo ► Проверяем обновления...
curl -fsSL -H "Authorization: token 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" "https://raw.githubusercontent.com/Rodenom/videoeditor-panel/main/app.py" -o "%TEMP%\app_new.py" 2>nul
if exist "%TEMP%\app_new.py" (
    fc /b "%TEMP%\app_new.py" "app.py" >nul 2>&1
    if errorlevel 1 (
        copy /y "%TEMP%\app_new.py" "app.py" >nul
        echo ✓ Обновление установлено
    ) else (
        echo ✓ Уже последняя версия
    )
) else (
    echo ⚠ Не удалось проверить обновления
)

echo.
echo ╔══════════════════════════════════════╗
echo ║       Запускаем панель...            ║
echo ╚══════════════════════════════════════╝
echo.
echo   Открой браузер: http://localhost:7777
echo.

python app.py
pause
