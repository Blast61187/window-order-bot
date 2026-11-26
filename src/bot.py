"""Telegram-бот: присылаете заявку текстом — получаете структурированный разбор."""

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

from parser import extract, format_response, invalid_by_operator_code, is_valid_contact
from storage import save_order
from wizard import START_FORM, build_form_conversation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HOW_TO_TEXT = (
    "Пришлите заявку текстом — например:\n"
    "«Нужно окно 1000х1200 (ШхВ), 2 шт. Павел, +375 29 000-00-21»\n\n"
    "Я разберу тип изделия, размеры, количество и контакты. Если чего-то не хватает — спрошу.\n\n"
    "Либо заполните заявку по шагам через кнопки — /form."
)
START_TEXT = f"Здравствуйте! {HOW_TO_TEXT}"
START_FORM_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("📋 Заполнить по форме", callback_data=START_FORM)]]
)

# сколько последних сообщений диалога храним только для raw_text в БД (аудит) — в модель
# они больше не идут, туда передаётся только текущее состояние заявки + новое сообщение
MAX_RAW_LOG = 20
DIALOG_TIMEOUT = timedelta(minutes=20)  # после паузы считаем, что начался новый разговор

FINISH_CALLBACK = "finish_dialog"
FINISH_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("✅ Это всё, больше ничего не добавлю", callback_data=FINISH_CALLBACK)]]
)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, reply_markup=START_FORM_KEYBOARD)


def _has_contact(data: dict) -> bool:
    return is_valid_contact(data.get("customer") or {})


def _reset_dialog(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.pop("order_state", None)
    context.chat_data["raw_log"] = []


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc)
    last_at = context.chat_data.get("last_message_at")
    if last_at and now - last_at > DIALOG_TIMEOUT:
        _reset_dialog(context)
    context.chat_data["last_message_at"] = now

    raw_log = context.chat_data.setdefault("raw_log", [])
    raw_log.append(update.message.text)
    del raw_log[:-MAX_RAW_LOG]

    # модели передаём текущее (уже известное) состояние заявки + только новое сообщение —
    # она обновляет состояние, а не разбирает всю переписку заново из сырого текста
    previous_state = context.chat_data.get("order_state")

    try:
        data = extract(update.message.text, previous_data=previous_state)
    except Exception:
        log.exception("Ошибка разбора заявки")
        await update.message.reply_text(
            "Не получилось разобрать сообщение из-за технической ошибки. Попробуйте ещё раз."
        )
        return

    reply_markup = None
    extra_note = None
    if not data.get("is_order"):
        _reset_dialog(context)
        reply_markup = START_FORM_KEYBOARD
        extra_note = HOW_TO_TEXT
    else:
        context.chat_data["order_state"] = data
        # заявка считается готовой к сохранению только когда заполнены и изделие, и контакт
        # (телефон или email) — без контакта связаться с покупателем всё равно не получится
        items_missing = any(item.get("missing_fields") for item in (data.get("items") or []))
        has_contact = _has_contact(data)

        if not items_missing and has_contact:
            save_order(update.effective_chat.id, update.effective_user.username, "\n---\n".join(raw_log), data)
            _reset_dialog(context)
            extra_note = "✅ Ваше обращение сохранено, мы свяжемся с вами в ближайшее время."
        else:
            # диалог ещё открыт (не хватает полей изделия и/или контакта) — даём покупателю
            # возможность его завершить, не дожидаясь, пока он сам всё допишет
            reply_markup = FINISH_KEYBOARD
            if not items_missing and not has_contact:
                contact_request = (
                    "Оставьте контактные данные: телефон (например, +375 29 000-00-00) или email — "
                    "чтобы мы могли связаться с вами."
                )
                bad_code = invalid_by_operator_code((data.get("customer") or {}).get("phone"))
                if bad_code:
                    extra_note = (
                        f"⚠️ Номер похож на белорусский, но код оператора «{bad_code}» не существует "
                        f"(реальные: 25, 29, 33, 44) — проверьте, пожалуйста.\n\n{contact_request}"
                    )
                else:
                    extra_note = contact_request

    reply_text = format_response(data)
    if extra_note:
        reply_text = f"{reply_text}\n\n{extra_note}"
    await update.message.reply_text(reply_text, reply_markup=reply_markup)


async def handle_finish_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    data = context.chat_data.get("order_state")
    raw = "\n---\n".join(context.chat_data.get("raw_log") or [])
    _reset_dialog(context)
    if data is None:
        return

    if _has_contact(data):
        save_order(query.message.chat.id, query.from_user.username, raw, data, status="incomplete_finalized_by_customer")
        note = "Принято, заявка передана менеджеру как есть — он свяжется, чтобы уточнить недостающее."
    else:
        # без контакта связаться всё равно не получится — в БД такую заявку не пишем
        note = "Без контактов заявку сохранить не можем."
    await query.message.reply_text(f"{note}\n\nЕсли нужно оформить ещё одну заявку — просто напишите.")


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
