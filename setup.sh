#!/bin/bash

echo ""
echo "=============================="
echo "  VideoEditor — Установка"
echo "=============================="
echo ""

# 1. Check macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
  echo "❌ Этот скрипт только для Mac"
  exit 1
fi

# 2. Install Homebrew if not installed
if ! command -v brew &>/dev/null; then
  echo "📦 Устанавливаем Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add brew to PATH for Apple Silicon
  if [[ -f "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  fi
else
  echo "✅ Homebrew уже установлен"
fi

# 3. Install Python 3 if not installed
if ! command -v python3 &>/dev/null; then
  echo "📦 Устанавливаем Python 3..."
  brew install python3
else
  echo "✅ Python $(python3 --version) уже установлен"
fi

# 4. Install ffmpeg if not installed
if ! command -v ffmpeg &>/dev/null; then
  echo "📦 Устанавливаем ffmpeg..."
  brew install ffmpeg
else
  echo "✅ ffmpeg уже установлен"
fi

# 5. Install Python packages
echo "📦 Устанавливаем Python библиотеки..."
pip3 install --quiet --upgrade \
  google-api-python-client \
  google-auth-oauthlib \
  google-auth-httplib2 \
  requests

echo ""
echo "=============================="
echo "  ✅ Установка завершена!"
echo "=============================="
echo ""
echo "Запускаем панель..."
echo ""

# 6. Launch panel
cd "$(dirname "$0")"
python3 app.py &
PANEL_PID=$!

# 7. Wait and open browser
sleep 2
open "http://localhost:7777"

echo "Панель запущена! Браузер открывается..."
echo "Чтобы остановить панель — нажми Ctrl+C"
echo ""

wait $PANEL_PID
