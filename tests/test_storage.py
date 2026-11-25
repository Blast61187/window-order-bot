"""Тесты storage.py на временной SQLite-базе (не трогают боевой data/orders.db)."""

import storage


def test_save_order_persists_order_and_items(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_FILE", tmp_path / "orders.db")

    data = {
        "items": [
            {"product_type": "Окно", "width_mm": 1000, "height_mm": 1200, "quantity": 2},
            {"product_type": "Дверь балконная", "width_mm": 700, "height_mm": 2100, "quantity": 1},
        ],
        "customer": {"name": "Павел", "phone": "+375 (29) 000-00-21", "email": None},
    }

    order_id = storage.save_order(123, "pavel_tg", "raw text", data, status="complete")

    orders = storage.list_orders()
    assert len(orders) == 1
    order = orders[0]
    assert order["id"] == order_id
    assert order["status"] == "complete"
    assert order["customer_name"] == "Павел"
    assert order["customer_phone"] == "+375 (29) 000-00-21"
    assert len(order["items"]) == 2
    assert order["items"][0]["product_type"] == "Окно"
    assert order["items"][1]["quantity"] == 1


def test_list_orders_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_FILE", tmp_path / "orders.db")
    data = {"items": [], "customer": {"name": None, "phone": None, "email": None}}

    for _ in range(3):
        storage.save_order(1, None, "x", data)

    assert len(storage.list_orders(limit=2)) == 2
    assert len(storage.list_orders(limit=50)) == 3
