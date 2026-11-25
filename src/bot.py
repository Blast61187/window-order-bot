"""Telegram-бот: присылаете заявку текстом — получаете структурированный разбор."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

from parser import extract, format_response
from storage import save_order
from wizard import START_FORM, build_form_conversation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

START_TEXT = (
    "Здравствуйте! Пришлите заявку текстом — например:\n"
    "«Нужно окно 1000х1200, 2 шт. Павел, +375 29 000-00-21»\n\n"
    "Я разберу тип изделия, размеры, количество и контакты. Если чего-то не хватает — спрошу.\n\n"
    "Либо заполните заявку по шагам через кнопки — /form."
)
START_FORM_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("📋 Заполнить по форме", callback_data=START_FORM)]]
)

MAX_HISTORY = 8  # сколько последних сообщений одного диалога держим как контекст
DIALOG_TIMEOUT = timedelta(minutes=20)  # после паузы считаем, что начался новый разговор

FINISH_CALLBACK = "finish_dialog"
FINISH_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("✅ Это всё, больше ничего не добавлю", callback_data=FINISH_CALLBACK)]]
)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, reply_markup=START_FORM_KEYBOARD)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc)
    last_at = context.chat_data.get("last_message_at")
    if last_at and now - last_at > DIALOG_TIMEOUT:
        context.chat_data["history"] = []
        context.chat_data.pop("last_saved", None)
    context.chat_data["last_message_at"] = now

    history = context.chat_data.setdefault("history", [])
    history.append(update.message.text)
    del history[:-MAX_HISTORY]

    try:
        data = extract("\n---\n".join(history))
    except Exception:
        log.exception("Ошибка разбора заявки")
        await update.message.reply_text(
            "Не получилось разобрать сообщение из-за технической ошибки. Попробуйте ещё раз."
        )
        return

    reply_markup = None
    if not data.get("is_order"):
        context.chat_data["history"] = []
        context.chat_data.pop("last_saved", None)
    else:
        has_missing = any(item.get("missing_fields") for item in (data.get("items") or []))
        if not has_missing:
            snapshot = json.dumps(
                {"items": data.get("items"), "customer": data.get("customer")},
                sort_keys=True,
                ensure_ascii=False,
            )
            if context.chat_data.get("last_saved") != snapshot:
                save_order(update.effective_chat.id, update.effective_user.username, "\n---\n".join(history), data)
                context.chat_data["last_saved"] = snapshot
        else:
            # диалог ещё открыт (бот ждёт уточнения) — даём покупателю возможность его завершить
            context.chat_data["pending_data"] = data
            context.chat_data["pending_raw"] = "\n---\n".join(history)
            reply_markup = FINISH_KEYBOARD

    await update.message.reply_text(format_response(data), reply_markup=reply_markup)


async def handle_finish_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    data = context.chat_data.pop("pending_data", None)
    raw = context.chat_data.pop("pending_raw", None)
    if data is None:
        return

    save_order(query.message.chat.id, query.from_user.username, raw, data, status="incomplete_finalized_by_customer")
    context.chat_data["history"] = []
    context.chat_data.pop("last_saved", None)

    await query.message.reply_text(
        "Принято, заявка передана менеджеру как есть — он свяжется, чтобы уточнить недостающее.\n\n"
        "Если нужно оформить ещё одну заявку — просто напишите."
    )


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пока умею читать только текст — голосовые, фото и файлы не разбираю.\n\n"
        "Опишите заявку словами или наберите /form, чтобы заполнить по шагам."
    )


def _check_llm_at_startup() -> None:
    try:
        extract("Нужно окно 1000х1200, 1 шт.")
        log.info("Проверка модели при старте: OK")
    except Exception:
        log.exception(
            "Проверка модели при старте НЕ прошла — проверьте GROQ_API_KEY/GROQ_MODEL. "
            "Бот всё равно запустится, но разбор заявок будет падать."
        )


def main() -> None:
    _check_llm_at_startup()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    state_file = Path(__file__).resolve().parent.parent / "data" / "bot_state.pickle"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=str(state_file))

    app = Application.builder().token(token).persistence(persistence).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CallbackQueryHandler(handle_finish_button, pattern=f"^{FINISH_CALLBACK}$"))
    app.add_handler(build_form_conversation())
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL & ~filters.TEXT & ~filters.COMMAND, handle_unsupported))
    log.info("Бот запущен, жду сообщения...")
    app.run_polling()


if __name__ == "__main__":
    main()
