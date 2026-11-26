#!/bin/bash
# Запуск/перезапуск Telegram-бота window-order-bot.
# Если бот уже работает — останавливает его и поднимает заново; если нет — просто запускает.
set -e

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PID_FILE="$PROJECT_DIR/data/bot.pid"
LOG_FILE="$PROJECT_DIR/data/bot.log"

mkdir -p "$PROJECT_DIR/data"

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE")"
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Останавливаю текущий процесс бота (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

cd "$PROJECT_DIR"
source .venv/bin/activate
cd src
nohup python bot.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 2
if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "Бот запущен, PID $NEW_PID."
    echo "Лог: $LOG_FILE"
else
    echo "Бот не запустился — смотрите лог: $LOG_FILE"
    tail -n 20 "$LOG_FILE"
    exit 1
fi
