"""Пошаговая форма (кнопки) — альтернативный способ оформить заявку без свободного текста.
Собранные данные приводятся к тому же виду, что и RESPONSE_SCHEMA из schema.py, и проходят
через тот же format_response()/save_order(), так что дальше по пайплайну это неотличимо от
заявки, разобранной моделью."""

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from parser import MAX_DIMENSION_MM, MIN_DIMENSION_MM, format_response, is_valid_email, normalize_phone
from storage import save_order

TYPE, UNIT, WIDTH, HEIGHT, QUANTITY, NAME, PHONE, EMAIL, CONFIRM = range(9)

PRODUCT_TYPES = ["Окно", "Дверь", "Дверь балконная", "Стеклопакет"]
UNITS = {"мм": 1, "см": 10, "м": 1000}
QUICK_QUANTITIES = ["1", "2", "3", "4", "5"]
OPERATORS = {"29 (А1/МТС)": "29", "33 (МТС)": "33", "44 (А1)": "44", "25 (life:))": "25"}

OTHER_TYPE = "__other_type__"
OTHER_QUANTITY = "__other_qty__"
OTHER_PHONE = "__other_phone__"
SKIP = "__skip__"
CANCEL = "__cancel__"
CONFIRM_YES = "__confirm_yes__"
START_FORM = "start_form"


def _kb(rows):
    return InlineKeyboardMarkup(rows)


def _cancel_row():
    return [InlineKeyboardButton("Отмена", callback_data=CANCEL)]


async def start_form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["form"] = {}
    buttons = [[InlineKeyboardButton(t, callback_data=t)] for t in PRODUCT_TYPES]
    buttons.append([InlineKeyboardButton("Другое", callback_data=OTHER_TYPE)])
    buttons.append(_cancel_row())

    if update.callback_query:
        await update.callback_query.answer()
        target = update.callback_query.message
    else:
        target = update.message
    await target.reply_text("Выберите тип изделия:", reply_markup=_kb(buttons))
    return TYPE


async def got_type_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    if query.data == OTHER_TYPE:
        await query.edit_message_text("Введите тип изделия текстом:")
        return TYPE
    context.user_data["form"]["product_type"] = query.data
    await query.edit_message_text(f"Тип изделия: {query.data}")
    return await _ask_unit(query.message)


async def got_type_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    product_type = update.message.text.strip()
    context.user_data["form"]["product_type"] = product_type
    await update.message.reply_text(f"Тип изделия: {product_type}")
    return await _ask_unit(update.message)


async def _ask_unit(message) -> int:
    buttons = [[InlineKeyboardButton(u, callback_data=u)] for u in UNITS]
    buttons.append(_cancel_row())
    await message.reply_text("В каких единицах укажете размеры?", reply_markup=_kb(buttons))
    return UNIT


async def got_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    context.user_data["form"]["unit_factor"] = UNITS[query.data]
    unit = query.data
    await query.edit_message_text(f"Единицы: {unit}")
    await query.message.reply_text(f"Ширина, в {unit}:")
    return WIDTH


MIN_DIMENSION_MM = 100
MAX_DIMENSION_MM = 6000


def _parse_number(text: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(match.group().replace(",", ".")) if match else None


async def got_width(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _parse_number(update.message.text)
    if value is None:
        await update.message.reply_text("Не нашёл число. Введите ширину числом:")
        return WIDTH

    factor = context.user_data["form"]["unit_factor"]
    unit = {v: k for k, v in UNITS.items()}[factor]
    width = round(value * factor)
    if not MIN_DIMENSION_MM <= width <= MAX_DIMENSION_MM:
        await update.message.reply_text(
            f"Получилось {width} мм — это странно для ширины окна/двери (ожидаю от "
            f"{MIN_DIMENSION_MM} до {MAX_DIMENSION_MM} мм). Проверьте число и введите ширину "
            f"ещё раз, в {unit}:"
        )
        return WIDTH
    context.user_data["form"]["width_mm"] = width

    await update.message.reply_text(f"Ширина: {width} мм\n\nВысота, в {unit}:")
    return HEIGHT


async def got_height(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _parse_number(update.message.text)
    if value is None:
        await update.message.reply_text("Не нашёл число. Введите высоту числом:")
        return HEIGHT

    factor = context.user_data["form"]["unit_factor"]
    unit = {v: k for k, v in UNITS.items()}[factor]
    height = round(value * factor)
    if not MIN_DIMENSION_MM <= height <= MAX_DIMENSION_MM:
        await update.message.reply_text(
            f"Получилось {height} мм — это странно для высоты окна/двери (ожидаю от "
            f"{MIN_DIMENSION_MM} до {MAX_DIMENSION_MM} мм). Проверьте число и введите высоту "
            f"ещё раз, в {unit}:"
        )
        return HEIGHT
    context.user_data["form"]["height_mm"] = height

    buttons = [[InlineKeyboardButton(q, callback_data=q) for q in QUICK_QUANTITIES]]
    buttons.append([InlineKeyboardButton("Другое количество", callback_data=OTHER_QUANTITY)])
    buttons.append(_cancel_row())
    await update.message.reply_text(f"Высота: {height} мм\n\nКоличество?", reply_markup=_kb(buttons))
    return QUANTITY


async def got_quantity_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    if query.data == OTHER_QUANTITY:
        await query.edit_message_text("Введите количество числом:")
        return QUANTITY
    context.user_data["form"]["quantity"] = int(query.data)
    await query.edit_message_text(f"Количество: {query.data}")
    return await _ask_name(query.message)


async def got_quantity_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = re.search(r"\d+", update.message.text)
    if not match:
        await update.message.reply_text("Не нашёл число. Введите количество числом:")
        return QUANTITY
    context.user_data["form"]["quantity"] = int(match.group())
    await update.message.reply_text(f"Количество: {match.group()}")
    return await _ask_name(update.message)


async def _ask_name(message) -> int:
    buttons = [[InlineKeyboardButton("Пропустить", callback_data=SKIP)], _cancel_row()]
    await message.reply_text("Имя покупателя (или пропустите):", reply_markup=_kb(buttons))
    return NAME


async def got_name_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    context.user_data["form"]["name"] = None
    await query.edit_message_text("Имя: не указано")
    return await _ask_phone(query.message)


async def got_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["form"]["name"] = update.message.text.strip()
    return await _ask_phone(update.message)


async def _ask_phone(message) -> int:
    buttons = [[InlineKeyboardButton(label, callback_data=code)] for label, code in OPERATORS.items()]
    buttons.append([InlineKeyboardButton("Другой формат номера", callback_data=OTHER_PHONE)])
    buttons.append([InlineKeyboardButton("Пропустить", callback_data=SKIP)])
    buttons.append(_cancel_row())
    await message.reply_text("Оператор покупателя (для маски номера):", reply_markup=_kb(buttons))
    return PHONE


async def got_phone_operator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    if query.data == SKIP:
        context.user_data["form"]["phone"] = None
        await query.edit_message_text("Телефон: не указан")
        return await _ask_email(query.message, context.user_data["form"])
    if query.data == OTHER_PHONE:
        await query.edit_message_text("Введите номер телефона целиком:")
        context.user_data["form"]["phone_operator"] = None
        return PHONE
    context.user_data["form"]["phone_operator"] = query.data
    await query.edit_message_text(f"Оператор: {query.data}")
    await query.message.reply_text("Введите 7 цифр номера (XXX-XX-XX):")
    return PHONE


async def got_phone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    digits = re.sub(r"\D", "", update.message.text)
    operator = context.user_data["form"].get("phone_operator")
    if operator and len(digits) == 7:
        digits = operator + digits
    if len(digits) < 7:
        await update.message.reply_text("Похоже на неполный номер. Введите ещё раз:")
        return PHONE
    context.user_data["form"]["phone"] = normalize_phone(digits)
    await update.message.reply_text(f"Телефон: {context.user_data['form']['phone']}")
    return await _ask_email(update.message, context.user_data["form"])


async def _ask_email(message, form: dict) -> int:
    # если телефон не указан, email становится обязательным — иначе с покупателем не связаться
    buttons = []
    if form.get("phone"):
        buttons.append([InlineKeyboardButton("Пропустить", callback_data=SKIP)])
        prompt = "Email (или пропустите):"
    else:
        prompt = "Телефон не указан, поэтому email обязателен — иначе мы не сможем с вами связаться:"
    buttons.append(_cancel_row())
    await message.reply_text(prompt, reply_markup=_kb(buttons))
    return EMAIL


async def got_email_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)
    # кнопка "Пропустить" тут есть только если телефон уже указан (см. _ask_email)
    context.user_data["form"]["email"] = None
    await query.edit_message_text("Email: не указан")
    return await _ask_confirm(query.message, context)


async def got_email_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    if not is_valid_email(email):
        await update.message.reply_text("Это не похоже на email (нужен формат вида name@example.com).")
        return await _ask_email(update.message, context.user_data["form"])
    context.user_data["form"]["email"] = email
    return await _ask_confirm(update.message, context)


def _build_data(form: dict) -> dict:
    return {
        "is_order": True,
        "not_order_reason": None,
        "items": [
            {
                "product_type": form.get("product_type"),
                "width_mm": form.get("width_mm"),
                "height_mm": form.get("height_mm"),
                "quantity": form.get("quantity"),
                "missing_fields": [],
            }
        ],
        "customer": {
            "name": form.get("name"),
            "phone": form.get("phone"),
            "email": form.get("email"),
        },
        "clarifying_question": None,
    }


async def _ask_confirm(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = _build_data(context.user_data["form"])
    context.user_data["form_data"] = data
    buttons = [[InlineKeyboardButton("✅ Отправить", callback_data=CONFIRM_YES)], _cancel_row()]
    await message.reply_text(
        f"Проверьте заявку:\n\n{format_response(data)}", reply_markup=_kb(buttons)
    )
    return CONFIRM


async def got_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == CANCEL:
        return await _cancel(update, context)

    data = context.user_data.pop("form_data")
    context.user_data.pop("form", None)
    save_order(query.message.chat.id, query.from_user.username, "(заполнено по форме)", data, status="complete")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("Готово, заявка передана менеджеру.")
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("form", None)
    context.user_data.pop("form_data", None)
    if update.callback_query:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
        await update.callback_query.message.reply_text("Форма отменена.")
    else:
        await update.message.reply_text("Форма отменена.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _cancel(update, context)


def build_form_conversation() -> ConversationHandler:
    text_filter = filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[
            CommandHandler("form", start_form),
            CallbackQueryHandler(start_form, pattern=f"^{START_FORM}$"),
        ],
        states={
            TYPE: [CallbackQueryHandler(got_type_button), MessageHandler(text_filter, got_type_text)],
            UNIT: [CallbackQueryHandler(got_unit)],
            WIDTH: [MessageHandler(text_filter, got_width)],
            HEIGHT: [MessageHandler(text_filter, got_height)],
            QUANTITY: [CallbackQueryHandler(got_quantity_button), MessageHandler(text_filter, got_quantity_text)],
            NAME: [CallbackQueryHandler(got_name_button), MessageHandler(text_filter, got_name_text)],
            PHONE: [CallbackQueryHandler(got_phone_operator), MessageHandler(text_filter, got_phone_text)],
            EMAIL: [CallbackQueryHandler(got_email_button), MessageHandler(text_filter, got_email_text)],
            CONFIRM: [CallbackQueryHandler(got_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        persistent=True,
        name="form_wizard",
    )
