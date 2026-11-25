"""Локальный прогон без Telegram: python cli.py "текст заявки" или --demo для примеров из задания."""

import sys

from dotenv import load_dotenv

load_dotenv()

from parser import extract, format_response

DEMO_MESSAGES = [
    "Здравствуйте! Нужно окно 1000х1200, 2 шт. Павел, +375 29 000-00-21.",
    "дверь балконная 70 на 210 см одна, тел 80290000022 анна.",
    "Сколько стоит остеклить балкон?",
]


def run(text: str) -> None:
    print(f"> {text}")
    data = extract(text)
    print(format_response(data))
    print()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] != "--demo":
        run(" ".join(sys.argv[1:]))
        return

    for message in DEMO_MESSAGES:
        run(message)


if __name__ == "__main__":
    main()
