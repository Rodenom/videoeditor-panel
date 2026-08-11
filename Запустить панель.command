#!/bin/bash

cd "$(dirname "$0")"

echo "=============================="
echo "  VideoEditor — Запуск"
echo "=============================="
echo ""

# Install Homebrew if missing
if ! command -v brew &>/dev/null; then
  echo "📦 Устанавливаем Homebrew (первый раз, ~5 мин)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -f "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  fi
fi

# Install ffmpeg if missing
if ! command -v ffmpeg &>/dev/null; then
  echo "📦 Устанавливаем ffmpeg (первый раз, ~5 мин)..."
  brew install ffmpeg
fi

# Install Python packages if missing
python3 -c "import googleapiclient" 2>/dev/null || {
  echo "📦 Устанавливаем библиотеки..."
  pip3 install --quiet google-api-python-client google-auth-oauthlib google-auth-httplib2 requests
}

echo ""
echo "✅ Всё готово! Запускаем панель..."
echo ""

sleep 2 && open "http://localhost:7777" &

echo "Панель работает на http://localhost:7777"
echo "Не закрывай это окно пока работаешь с панелью."
echo ""

# Restart loop: when a buyer clicks "Обновить" in the panel, the server
# process exits with code 42 to reload the just-downloaded new app.py.
# Without this loop the process would just die and stay dead.
while true; do
  python3 app.py
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 42 ]; then
    echo "🔄 Обновление применено, перезапуск..."
    sleep 1
  else
    break
  fi
done
