import argparse
import asyncio
import json
import logging

from xazdent_ai import make_card

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def main(input_path: str) -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        product_data = json.load(f)

    card_text = await make_card(product_data)
    print(card_text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XazDent mahsulot kartochkasi tayyorlash")
    parser.add_argument("input", help="Mahsulot JSON fayl yo'li")
    args = parser.parse_args()
    asyncio.run(main(args.input))
