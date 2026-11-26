"""Разбор свободной заявки на окна/двери/стеклопакеты в структуру.

Извлечение полей делает LLM через Groq (OpenAI-совместимый API, бесплатный, без суффикса
':free' — весь API бесплатен с лимитами по RPM) в режиме JSON-ответа; схема полей из schema.py
передаётся текстом в системном промпте — любое отсутствующее поле обязано прийти как null,
модели запрещено додумывать значения. Форматирование телефона и финального текста ответа —
чистый детерминированный Python, чтобы маска номера и текст ответа не зависели от прихотей
модели.
"""

import json
import os
import re

from schema import RESPONSE_SCHEMA

MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = f"""\
Ты разбираешь входящие сообщения покупателей компании, изготавливающей окна, двери и \
стеклопакеты. Твоя единственная задача — извлечь структурированные данные и вернуть их \
ОДНИМ JSON-объектом, строго соответствующим следующей JSON-схеме, без каких-либо пояснений, \
markdown-разметки или текста до/после JSON:

{json.dumps(RESPONSE_SCHEMA, ensure_ascii=False, indent=2)}

Главное правило: НИЧЕГО НЕ ВЫДУМЫВАЙ. Если какого-то значения нет в тексте явно — \
возвращай null и перечисляй поле в missing_fields. Не подставляй значения по умолчанию \
(например, не считай, что количество равно 1, если число не названо явно).

Если в сообщении несколько изделий — опиши каждое отдельным объектом в items. Контакты \
(имя, телефон, email) считаются общими для всех изделий в сообщении.

Если сообщение не является заявкой (вопрос о цене без конкретного изделия, приветствие, \
не по теме) — верни is_order=false, items пустой массив, customer с null-полями, и коротко \
объясни в not_order_reason, почему это не похоже на заявку.

Иногда тебе дают не просто новое сообщение, а ТЕКУЩЕЕ СОСТОЯНИЕ заявки (JSON по этой же схеме, \
уже извлечённое из предыдущих сообщений этого же покупателя) плюс новое сообщение. В этом случае \
твоя задача — вернуть ОБНОВЛЁННОЕ состояние, а не разбирать новое сообщение с нуля:
- если новое сообщение явно меняет или уточняет какое-то поле (например, даёт новый телефон \
взамен уже известного, досообщает недостающий размер, поправляет имя) — замени именно это поле \
новым значением;
- поля, которые новое сообщение не затрагивает, оставляй как в текущем состоянии — не теряй уже \
известные данные и не придумывай причин их менять;
- если новое сообщение явно описывает ДОПОЛНИТЕЛЬНОЕ отдельное изделие (например, "и ещё дверь \
700х2100") — добавь его отдельным элементом в items, не трогая и не дублируя уже имеющиеся;
- если новое сообщение совсем не по теме заявки — верни is_order=false, как обычно (даже если \
текущее состояние было про заявку).
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ["GROQ_API_KEY"],
        )
    return _client


def extract(text: str, previous_data: dict | None = None) -> dict:
    """Вызывает модель и возвращает провалидированный dict по RESPONSE_SCHEMA.

    Если передан previous_data (состояние заявки с прошлых сообщений этого диалога), модель
    обновляет его новым сообщением, а не разбирает текст с нуля — так новое сообщение не может
    случайно продублировать уже известное изделие или потерять уже известный контакт."""
    user_content = text
    if previous_data:
        user_content = (
            "Текущее состояние заявки (JSON):\n"
            f"{json.dumps(previous_data, ensure_ascii=False)}\n\n"
            "Новое сообщение от покупателя:\n"
            f"{text}"
        )

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    content = response.choices[0].message.content.strip()
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    data = json.loads(content)
    _validate_dimensions(data)
    _validate_email(data)
    return data


MIN_DIMENSION_MM = 100
MAX_DIMENSION_MM = 6000

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str | None) -> bool:
    return bool(email) and bool(EMAIL_PATTERN.match(email.strip()))


def has_enough_digits(phone: str | None, min_digits: int = 7) -> bool:
    return bool(phone) and len(re.sub(r"\D", "", phone)) >= min_digits


def is_valid_phone(phone: str | None) -> bool:
    """Либо не похоже на белорусский формат (тогда доверяем просто количеству цифр — может,
    это другая страна), либо похоже — и тогда код оператора обязан быть реальным."""
    if not phone:
        return False
    code = _by_mobile_code(phone)
    if code is not None:
        return code in BY_MOBILE_CODES
    return has_enough_digits(phone)


def invalid_by_operator_code(phone: str | None) -> str | None:
    """Если phone похож по форме на белорусский мобильный, но код оператора не существует —
    возвращает этот код (чтобы явно предупредить), иначе None."""
    if not phone:
        return None
    code = _by_mobile_code(phone)
    if code is not None and code not in BY_MOBILE_CODES:
        return code
    return None


def is_valid_contact(customer: dict) -> bool:
    """Телефон или email, которые реально похожи на телефон/email, а не на любую непустую строку."""
    return is_valid_phone(customer.get("phone")) or is_valid_email(customer.get("email"))


def _validate_email(data: dict) -> None:
    """Если то, что модель вернула как email, не похоже на email (нет @ и домена) — считаем,
    что email не указан, а не что это и есть email."""
    customer = data.get("customer") or {}
    email = customer.get("email")
    if email and not is_valid_email(email):
        customer["email"] = None


def _validate_dimensions(data: dict) -> None:
    """Модель могла принять за размер случайное число из текста (опечатку, телефон и т.п.).
    Ширина/высота вне разумного диапазона для окон/дверей считается непонятой, а не истинной —
    обнуляем её и просим уточнить, вместо того чтобы молча поверить сомнительному значению."""
    invalidated_fields = set()
    for item in data.get("items") or []:
        for field in ("width_mm", "height_mm"):
            value = item.get(field)
            if value is not None and not (MIN_DIMENSION_MM <= value <= MAX_DIMENSION_MM):
                item[field] = None
                if field not in item["missing_fields"]:
                    item["missing_fields"].append(field)
                invalidated_fields.add(field)

    if invalidated_fields:
        data["clarifying_question"] = (
            "уточните размеры — то, что удалось найти в сообщении, не похоже на реальные "
            f"размеры окна/двери (ожидаю от {MIN_DIMENSION_MM} до {MAX_DIMENSION_MM} мм)."
        )


_PRODUCT_LABELS = {
    "product_type": "тип изделия",
    "width_mm": "ширину",
    "height_mm": "высоту",
    "quantity": "количество",
}


BY_MOBILE_CODES = {"25", "29", "33", "44"}  # реальные коды мобильных операторов РБ


def _by_mobile_code(raw: str) -> str | None:
    """Если raw похож по форме на белорусский мобильный (375/80 + 9 цифр, либо голые 9 цифр) —
    возвращает двузначный код оператора (даже если он несуществующий), иначе None."""
    digits = re.sub(r"\D", "", raw)
    is_by_prefixed = len(digits) >= 9 and (digits.startswith("375") or digits.startswith("80"))
    is_bare_national = len(digits) == 9  # уже "код оператора (2) + номер абонента (7)", без 375/80
    if (is_by_prefixed or is_bare_national) and len(digits[-9:]) == 9:
        return digits[-9:][:2]
    return None


def normalize_phone(raw: str) -> str:
    """Приводит белорусский мобильный номер к виду +375 (29) 000-00-21.
    Если похоже на белорусский номер, но код оператора не существует (например, 28), или номер
    не похож на белорусский мобильный вообще — возвращает исходную строку с '+' при его наличии,
    а не навязывает заведомо неверную маску."""
    digits = re.sub(r"\D", "", raw)
    code = _by_mobile_code(raw)
    if code in BY_MOBILE_CODES:
        national = digits[-9:]
        subscriber = national[2:]
        return f"+375 ({code}) {subscriber[:3]}-{subscriber[3:5]}-{subscriber[5:7]}"

    return raw if raw.strip().startswith("+") else f"+{digits}" if digits else raw


def format_response(data: dict) -> str:
    if not data.get("is_order"):
        # not_order_reason — внутренняя классификация модели, клиенту её не показываем
        return "Это не похоже на заявку на окна/двери/стеклопакеты."

    items = data.get("items") or []
    customer = data.get("customer") or {}
    lines = []

    multiple = len(items) > 1
    for i, item in enumerate(items, start=1):
        if multiple:
            lines.append(f"Изделие {i}:")

        product_type = item.get("product_type")
        lines.append(f"Тип изделия: {product_type if product_type else '— не указан —'};")

        width = item.get("width_mm")
        height = item.get("height_mm")
        quantity = item.get("quantity")
        if width is not None and height is not None:
            size = f"{int(width)}х{int(height)}мм"
        elif width is not None or height is not None:
            size = f"{int(width) if width is not None else '—'}х{int(height) if height is not None else '—'}мм"
        else:
            size = "— не указаны —"
        qty_part = f"{int(quantity)}шт" if quantity is not None else "кол-во не указано"
        lines.append(f"Размеры, ШхВ: {size} – {qty_part};")

        missing = item.get("missing_fields") or []
        if missing:
            missing_ru = ", ".join(_PRODUCT_LABELS.get(f, f) for f in missing)
            lines.append(f"⚠️ Не хватает данных: {missing_ru};")

        if multiple:
            lines.append("")

    name = customer.get("name")
    phone = customer.get("phone")
    email = customer.get("email")
    if name or phone or email:
        if name:
            lines.append(f"ФИО покупателя: {name};")
        if phone:
            lines.append(f"Тел.: {normalize_phone(phone)};")
        if email:
            lines.append(f"Email: {email};")
    else:
        lines.append("Контакты покупателя: не указаны.")

    question = data.get("clarifying_question")
    if question:
        # модель иногда всё равно добавляет своё "уточните, пожалуйста" — снимаем дубль
        question = re.sub(r"^уточните,?\s*пожалуйста,?\s*", "", question.strip(), flags=re.IGNORECASE)
        lines.append("")
        lines.append(f"Уточните, пожалуйста: {question}")

    return "\n".join(lines).strip()
