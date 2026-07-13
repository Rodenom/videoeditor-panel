#!/bin/bash
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Video Editor — Установка (Mac)     ║"
echo "╚══════════════════════════════════════╝"
echo ""

cd "$(dirname "$0")"

# Добавляем Homebrew в PATH для Apple Silicon и Intel
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Добавляем в профиль навсегда
if ! grep -q 'homebrew/bin' ~/.zprofile 2>/dev/null; then
  echo 'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"' >> ~/.zprofile
fi

# Check Homebrew
if ! command -v brew &>/dev/null; then
  echo "► Устанавливаем Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
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

# Check ffmpeg with drawtext support
echo "► Проверяем ffmpeg..."
check_drawtext() { ffmpeg -filters 2>&1 | grep -q drawtext; }

if ! command -v ffmpeg &>/dev/null; then
  echo "► Устанавливаем ffmpeg..."
  brew install ffmpeg
fi

if ! check_drawtext; then
  echo "► ffmpeg без drawtext — переустанавливаем..."
  brew uninstall ffmpeg-full 2>/dev/null || true
  brew uninstall ffmpeg 2>/dev/null || true
  brew install ffmpeg
fi

if check_drawtext; then
  echo "✓ ffmpeg готов"
else
  echo "⚠ ffmpeg установлен (текст на видео недоступен, остальное работает)"
fi

# Install Python dependencies (robust — some systems block plain pip install
# with "externally-managed-environment", so we verify and fall back)
echo "► Устанавливаем Python библиотеки..."
PY_DEPS="google-auth google-auth-oauthlib google-api-python-client anthropic httplib2 PySocks requests"
check_deps() { python3 -c "import google_auth_oauthlib, googleapiclient, requests" 2>/dev/null; }

python3 -m pip install --quiet $PY_DEPS 2>/dev/null
if ! check_deps; then
  echo "  ⚠ Обычная установка не сработала, пробуем ещё раз..."
  python3 -m pip install --quiet --break-system-packages $PY_DEPS 2>/dev/null
fi
if ! check_deps; then
  python3 -m pip install --quiet --user $PY_DEPS 2>/dev/null
fi
if ! check_deps; then
  echo ""
  echo "❌ Не удалось установить Python-библиотеки автоматически."
  echo "   Открой терминал в этой папке и выполни вручную:"
  echo "   python3 -m pip install --break-system-packages $PY_DEPS"
  echo ""
  read -p "Нажми Enter чтобы закрыть..."
  exit 1
fi
echo "✓ Библиотеки установлены"

# Install SSL certificates
PY_CERT=$(find /Applications/Python* -name "Install Certificates.command" 2>/dev/null | head -1)
if [ -n "$PY_CERT" ]; then
  bash "$PY_CERT" &>/dev/null
fi

# Auto-update app.py from GitHub (only upgrade, never downgrade)
echo "► Проверяем обновления..."
UPDATE_URL="https://raw.githubusercontent.com/Rodenom/videoeditor-panel/main/app.py"
TMP_FILE="/tmp/app_new.py"
if curl -fsSL "$UPDATE_URL" -o "$TMP_FILE" 2>/dev/null; then
  NEW_VER=$(grep -o 'VERSION = "[^"]*"' "$TMP_FILE" | grep -o '[0-9.]*')
  CUR_VER=$(grep -o 'VERSION = "[^"]*"' "app.py" 2>/dev/null | grep -o '[0-9.]*')
  if [ -n "$NEW_VER" ] && [ "$(printf '%s\n' "$NEW_VER" "$CUR_VER" | sort -V | tail -1)" = "$NEW_VER" ] && [ "$NEW_VER" != "$CUR_VER" ]; then
    cp "$TMP_FILE" "app.py"
    echo "✓ Обновление $CUR_VER → $NEW_VER установлено"
  else
    echo "✓ Версия $CUR_VER актуальная"
  fi
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Запускаем панель...           ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Kill any old process on port 7777
lsof -ti:7777 | xargs kill -9 2>/dev/null
sleep 1

sleep 2 && open http://localhost:7777 &
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
