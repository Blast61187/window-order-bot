"""SQLite-хранилище готовых заявок — для просмотра и выборок менеджером.

Используется встроенный sqlite3 (без дополнительных зависимостей): один файл на диске,
без отдельного сервера БД — достаточно для объёма заявок одного бота. Заказы и их изделия
лежат в двух таблицах (1 заказ — N изделий), а не одной JSON-колонкой, чтобы по ним можно
было нормально фильтровать/агрегировать (SELECT * FROM order_items WHERE product_type = ...)."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from parser import normalize_phone

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "orders.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    username TEXT,
    status TEXT NOT NULL,
    raw_text TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_type TEXT,
    width_mm INTEGER,
    height_mm INTEGER,
    quantity INTEGER
);
"""


def _get_connection() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def save_order(chat_id: int, username: str | None, raw_text: str, data: dict, status: str = "complete") -> int:
    """Пишет заказ и его изделия одной транзакцией, возвращает id заказа."""
    customer = data.get("customer") or {}
    phone = customer.get("phone")
    conn = _get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO orders (created_at, chat_id, username, status, raw_text,
                                     customer_name, customer_phone, customer_email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    chat_id,
                    username,
                    status,
                    raw_text,
                    customer.get("name"),
                    normalize_phone(phone) if phone else None,
                    customer.get("email"),
                ),
            )
            order_id = cur.lastrowid
            for item in data.get("items") or []:
                conn.execute(
                    """
                    INSERT INTO order_items (order_id, product_type, width_mm, height_mm, quantity)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        item.get("product_type"),
                        item.get("width_mm"),
                        item.get("height_mm"),
                        item.get("quantity"),
                    ),
                )
        return order_id
    finally:
        conn.close()


def list_orders(limit: int = 50) -> list[dict]:
    """Последние заказы вместе с их изделиями — для ручного просмотра/отладки."""
    conn = _get_connection()
    conn.row_factory = sqlite3.Row
    try:
        orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for order in orders:
            items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)).fetchall()
            result.append({**dict(order), "items": [dict(item) for item in items]})
        return result
    finally:
        conn.close()
