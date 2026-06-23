#!/bin/bash
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Video Editor — Установка (Mac)     ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Homebrew
if ! command -v brew &>/dev/null; then
  echo "► Устанавливаем Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  echo "✓ Homebrew уже установлен"
fi

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "► Устанавливаем Python..."
  brew install python
else
  PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  echo "✓ Python $PY_VER уже установлен"
fi

# Check ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "► Устанавливаем ffmpeg..."
  brew install ffmpeg
else
  echo "✓ ffmpeg уже установлен"
fi

# Install Python dependencies
echo "► Устанавливаем Python библиотеки..."
pip3 install --quiet google-auth google-auth-oauthlib google-api-python-client anthropic httplib2 PySocks

# Install SSL certificates
echo "► Устанавливаем SSL сертификаты..."
PY_CERT=$(find /Applications/Python* -name "Install Certificates.command" 2>/dev/null | head -1)
if [ -n "$PY_CERT" ]; then
  bash "$PY_CERT" &>/dev/null
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Установка завершена!          ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "► Запускаем панель..."
echo ""

cd "$(dirname "$0")"
python3 app.py
