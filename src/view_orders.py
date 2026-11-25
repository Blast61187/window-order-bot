"""Просмотр сохранённых заявок без отдельного SQLite-клиента: python view_orders.py [N]."""

import sys

from storage import list_orders


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    orders = list_orders(limit)
    if not orders:
        print("Заявок пока нет.")
        return

    for order in orders:
        print(f"#{order['id']} [{order['status']}] {order['created_at']} чат {order['chat_id']} (@{order['username']})")
        for item in order["items"]:
            size = f"{item['width_mm']}x{item['height_mm']}мм" if item["width_mm"] else "размеры не указаны"
            qty = item["quantity"] if item["quantity"] is not None else "кол-во не указано"
            print(f"  - {item['product_type'] or 'тип не указан'}: {size}, {qty}")
        print(f"  Контакты: {order['customer_name']}, {order['customer_phone']}, {order['customer_email']}")
        print()


if __name__ == "__main__":
    main()
