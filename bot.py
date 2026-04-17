import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from dotenv import load_dotenv

from scraper import scrape_aliexpress
from ai_processor import make_card

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

ALIEXPRESS_DOMAINS = ["aliexpress.com", "aliexpress.ru", "a.aliexpress.com", "s.click.aliexpress.com"]

def is_aliexpress_link(text: str) -> bool:
    return any(domain in text for domain in ALIEXPRESS_DOMAINS)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Salom! Men <b>XazDent Hamkor Bot</b>man.\n\n"
        "📦 AliExpress mahsulot havolasini yuboring — men sizga tayyor kartochka yasab beraman:\n\n"
        "• 📝 Nomi va tavsifi (o'zbekcha)\n"
        "• 🖼 Rasmlari\n"
        "• 📐 Razmer / variantlar\n"
        "• 💴 Narxi (Yuan / USD / So'm)\n"
        "• 🔢 Artikul va minimal buyurtma\n\n"
        "Havolani yuboring! ⬇️",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_link(message: Message):
    text = message.text.strip()

    if not is_aliexpress_link(text):
        await message.answer(
            "⚠️ Faqat <b>AliExpress</b> havolalarini qabul qilaman.\n\n"
            "Masalan:\n<code>https://www.aliexpress.com/item/1234567890.html</code>",
            parse_mode="HTML"
        )
        return

    processing_msg = await message.answer("⏳ Mahsulot ma'lumotlari yuklanmoqda...")

    try:
        # 1. Scrape
        await bot.edit_message_text(
            "🔍 AliExpress sahifasi o'qilmoqda...",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        product_data = await scrape_aliexpress(text)

        if not product_data:
            await bot.edit_message_text(
                "❌ Mahsulot ma'lumotlarini olishda xatolik.\n"
                "Iltimos, havolani tekshirib qayta yuboring.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            return

        # 2. AI kartochka
        await bot.edit_message_text(
            "🤖 AI kartochka tayyorlamoqda...",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        card_text = await make_card(product_data)

        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

        # 3. Rasmlarni yuborish
        photos = product_data.get("images", [])
        if photos:
            from aiogram.types import InputMediaPhoto
            media = []
            for i, url in enumerate(photos[:8]):  # Telegram max 10, biz 8 ta
                if i == 0:
                    media.append(InputMediaPhoto(media=url, caption=card_text, parse_mode="HTML"))
                else:
                    media.append(InputMediaPhoto(media=url))
            await message.answer_media_group(media)
        else:
            await message.answer(card_text, parse_mode="HTML")

        # 4. Xom JSON (kopi-paste uchun)
        await message.answer(
            "📋 <b>Xom ma'lumotlar (XazDentga yuklash uchun):</b>",
            parse_mode="HTML"
        )
        import json
        raw = {
            "name": product_data.get("title", ""),
            "price_uzs": product_data.get("price_uzs", 0),
            "price_usd": product_data.get("price_usd", 0),
            "description": product_data.get("description", ""),
            "images": photos[:5],
            "variants": product_data.get("variants", []),
            "min_order": product_data.get("min_order", 1),
            "artikul": product_data.get("product_id", ""),
        }
        await message.answer(
            f"<code>{json.dumps(raw, ensure_ascii=False, indent=2)}</code>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await bot.edit_message_text(
            f"❌ Xatolik yuz berdi: {str(e)[:200]}\n\nQayta urinib ko'ring.",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )

async def main():
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
