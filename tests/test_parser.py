"""Тесты чистых функций parser.py (без сети и без API-ключа — extract() не вызывается)."""

from parser import format_response, normalize_phone


def test_normalize_phone_with_plus_375():
    assert normalize_phone("+375 29 000-00-21") == "+375 (29) 000-00-21"


def test_normalize_phone_local_80_prefix():
    assert normalize_phone("80290000022") == "+375 (29) 000-00-22"


def test_normalize_phone_bare_national_number():
    assert normalize_phone("295485997") == "+375 (29) 548-59-97"


def test_normalize_phone_foreign_number_untouched():
    assert normalize_phone("+1 202 555 0176") == "+1 202 555 0176"


def test_normalize_phone_empty_string():
    assert normalize_phone("") == ""


def _complete_order(**customer_overrides):
    customer = {"name": "Павел", "phone": "+375 29 000-00-21", "email": None}
    customer.update(customer_overrides)
    return {
        "is_order": True,
        "not_order_reason": None,
        "items": [
            {"product_type": "Окно", "width_mm": 1000, "height_mm": 1200, "quantity": 2, "missing_fields": []}
        ],
        "customer": customer,
        "clarifying_question": None,
    }


def test_format_response_complete_order_matches_expected_example():
    result = format_response(_complete_order())
    assert result == (
        "Тип изделия: Окно;\n"
        "Размеры, ШхВ: 1000х1200мм – 2шт;\n"
        "ФИО покупателя: Павел;\n"
        "Тел.: +375 (29) 000-00-21;"
    )


def test_format_response_missing_fields_lists_them():
    data = {
        "is_order": True,
        "not_order_reason": None,
        "items": [
            {
                "product_type": "Дверь балконная",
                "width_mm": 700,
                "height_mm": 2100,
                "quantity": None,
                "missing_fields": ["quantity"],
            }
        ],
        "customer": {"name": None, "phone": None, "email": None},
        "clarifying_question": "количество дверей балконных.",
    }
    result = format_response(data)
    assert "Не хватает данных: количество" in result
    assert "Контакты покупателя: не указаны." in result
    assert "Уточните, пожалуйста: количество дверей балконных." in result


def test_format_response_strips_duplicated_lead_in_from_model():
    data = {
        "is_order": True,
        "not_order_reason": None,
        "items": [
            {
                "product_type": "Окно",
                "width_mm": 1000,
                "height_mm": None,
                "quantity": 1,
                "missing_fields": ["height_mm"],
            }
        ],
        "customer": {"name": None, "phone": None, "email": None},
        "clarifying_question": "Уточните, пожалуйста, высоту окна.",
    }
    result = format_response(data)
    assert "Уточните, пожалуйста: Уточните" not in result
    assert "Уточните, пожалуйста: высоту окна." in result


def test_format_response_multiple_items_are_numbered():
    data = {
        "is_order": True,
        "not_order_reason": None,
        "items": [
            {"product_type": "Окно", "width_mm": 1000, "height_mm": 1200, "quantity": 2, "missing_fields": []},
            {
                "product_type": "Дверь балконная",
                "width_mm": 700,
                "height_mm": 2100,
                "quantity": 1,
                "missing_fields": [],
            },
        ],
        "customer": {"name": "Ирина", "phone": None, "email": "irina@mail.ru"},
        "clarifying_question": None,
    }
    result = format_response(data)
    assert "Изделие 1:" in result
    assert "Изделие 2:" in result
    assert "Email: irina@mail.ru;" in result


def test_format_response_not_an_order():
    data = {
        "is_order": False,
        "not_order_reason": "Это вопрос о цене, без конкретного изделия.",
        "items": [],
        "customer": {"name": None, "phone": None, "email": None},
        "clarifying_question": None,
    }
    result = format_response(data)
    assert "не похоже на заявку" in result
    assert "Это вопрос о цене" in result
