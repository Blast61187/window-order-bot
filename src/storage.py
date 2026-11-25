"""Запись готовых заявок в JSONL на диск — для просмотра менеджером."""

import json
from datetime import datetime, timezone
from pathlib import Path

ORDERS_FILE = Path(__file__).resolve().parent.parent / "data" / "orders.jsonl"


def save_order(chat_id: int, username: str | None, raw_text: str, data: dict, status: str = "complete") -> None:
    ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "username": username,
        "status": status,  # "complete" или "incomplete_finalized_by_customer"
        "raw_text": raw_text,
        "items": data.get("items"),
        "customer": data.get("customer"),
    }
    with ORDERS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
