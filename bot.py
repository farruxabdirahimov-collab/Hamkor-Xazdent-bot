import asyncio
import logging
import os
import aiohttp
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

# Barcha AliExpress domenlar + short linklar
ALIEXPRESS_DOMAINS = [
    "aliexpress.com",
    "aliexpress.ru",
    "a.aliexpress.com",
    "s.click.aliexpress.com",
    "click.aliexpress.com",
    "ali.click",          # ← yangi
    "alx.click",          # ← yangi
    "aliclick.com",       # ← yangi
]

def is_aliexpress_link(text: str) -> bool:
    return any(domain in text for domain in ALIEXPRESS_DOMAINS)

def extract_url(text: str) -> str | None:
    """Matndan URL ni ajratib olish"""
    import re
    pattern = r'https?://[^\s]+'
    match = re.search(pattern, text)
    return match.group(0) if match else None

async def resolve_short_url(url: str) -> str:
    """Short URL ni redirect orqali haqiqiy URL ga aylantirish"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
                ssl=False,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            ) as resp:
                final_url = str(resp.url)
                logger.info(f"Redirect: {url} → {final_url}")
                return final_url
    except Exception as e:
        logger.error(f"Redirect xatolik: {e}")
        return url

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
        "✅ Qisqa havola (ali.click) ham qabul qilinadi!\n\n"
        "Havolani yuboring! ⬇️",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_link(message: Message):
    text = message.text.strip()

    # URL ni matndan ajratib olish
    url = extract_url(text)

    if not url:
        await message.answer(
            "⚠️ Havola topilmadi.\n\n"
            "AliExpress mahsulot havolasini yuboring.\n"
            "Qisqa havola (ali.click/...) ham ishlaydi! ✅",
        )
        return

    # AliExpress ekanligini tekshirish
    if not is_aliexpress_link(url):
        # Ehtimol short link redirect qilar — sinab ko'ramiz
        processing_msg = await message.answer("🔍 Havola tekshirilmoqda...")
        resolved = await resolve_short_url(url)

        if not is_aliexpress_link(resolved):
            await bot.edit_message_text(
                "⚠️ Faqat <b>AliExpress</b> havolalarini qabul qilaman.\n\n"
                "Qisqa havola (ali.click/...) ham ishlaydi ✅",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                parse_mode="HTML"
            )
            return
        url = resolved
    else:
        processing_msg = await message.answer("⏳ Mahsulot ma'lumotlari yuklanmoqda...")

    try:
        # Short link bo'lsa resolve qilamiz
        if any(d in url for d in ["ali.click", "alx.click"]):
            await bot.edit_message_text(
                "🔗 Havola ochilmoqda...",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            url = await resolve_short_url(url)

        # Scrape
        await bot.edit_message_text(
            "🔍 AliExpress sahifasi o'qilmoqda...",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        product_data = await scrape_aliexpress(url)

        if not product_data:
            await bot.edit_message_text(
                "❌ Mahsulot ma'lumotlarini olishda xatolik.\n"
                "Iltimos, havolani tekshirib qayta yuboring.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            return

        # AI kartochka
        await bot.edit_message_text(
            "🤖 AI kartochka tayyorlamoqda...",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        card_text = await make_card(product_data)

        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

        # Rasmlarni yuborish
        photos = product_data.get("images", [])
        if photos:
            from aiogram.types import InputMediaPhoto
            media = []
            for i, photo_url in enumerate(photos[:8]):
                if i == 0:
                    media.append(InputMediaPhoto(media=photo_url, caption=card_text, parse_mode="HTML"))
                else:
                    media.append(InputMediaPhoto(media=photo_url))
            await message.answer_media_group(media)
        else:
            await message.answer(card_text, parse_mode="HTML")

        # Xom JSON
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
        await message.answer("📋 <b>Xom ma'lumotlar (XazDentga yuklash uchun):</b>", parse_mode="HTML")
        await message.answer(
            f"<code>{json.dumps(raw, ensure_ascii=False, indent=2)}</code>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            await bot.edit_message_text(
                f"❌ Xatolik yuz berdi: {str(e)[:200]}\n\nQayta urinib ko'ring.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
        except:
            await message.answer(f"❌ Xatolik: {str(e)[:200]}")

async def main():
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
