import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.filters import CommandStart
from dotenv import load_dotenv

from scraper import scrape_aliexpress, parse_manual_input
from ai_processor import make_card
from xazdent_uploader import upload_to_xazdent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

product_cache = {}

ALIEXPRESS_DOMAINS = [
    "aliexpress.com", "aliexpress.ru", "a.aliexpress.com",
    "s.click.aliexpress.com", "click.aliexpress.com",
    "ali.click", "alx.click", "aliclick.com",
    "1688.com", "detail.1688.com", "s.1688.com",
]

def is_aliexpress_link(text: str) -> bool:
    return any(domain in text for domain in ALIEXPRESS_DOMAINS)

def extract_url(text: str) -> str | None:
    import re
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else None

async def resolve_short_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True, ssl=False,
                headers={"User-Agent": "Mozilla/5.0"}) as resp:
                return str(resp.url)
    except Exception as e:
        logger.error(f"Redirect xatolik: {e}")
        return url

async def send_card(message: Message, product_data: dict, card_text: str):
    photos = product_data.get("images", [])
    if photos:
        media = []
        for i, photo_url in enumerate(photos[:8]):
            if i == 0:
                media.append(InputMediaPhoto(media=photo_url, caption=card_text, parse_mode="HTML"))
            else:
                media.append(InputMediaPhoto(media=photo_url))
        try:
            await message.answer_media_group(media)
        except:
            await message.answer(card_text, parse_mode="HTML")
    else:
        await message.answer(card_text, parse_mode="HTML")

    raw = {
        "name": product_data.get("title", ""),
        "price_uzs": product_data.get("price_uzs", 0),
        "price_usd": product_data.get("price_usd", 0),
        "images": photos[:5],
        "variants": product_data.get("variants", []),
        "artikul": product_data.get("product_id", ""),
    }
    await message.answer("📋 <b>Xom ma'lumotlar:</b>", parse_mode="HTML")
    await message.answer(f"<code>{json.dumps(raw, ensure_ascii=False, indent=2)}</code>", parse_mode="HTML")

    product_id = product_data.get("product_id", "")
    product_cache[product_id] = product_data

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ XazDentga yuklash", callback_data=f"upload:{product_id}")
    ]])
    await message.answer("👆 Kartochka tayyor!\nXazDent katalogiga yuklash uchun tugmani bosing:", reply_markup=keyboard)

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Salom! Men <b>XazDent Hamkor Bot</b>man.\n\n"
        "📎 <b>Havola orqali:</b>\n"
        "AliExpress yoki 1688 havolasini yuboring\n\n"
        "✍️ <b>Qo'lda kiritish:</b>\n"
        "<code>nom: Dental turbina\n"
        "narx: 850000\n"
        "tavsif: Osstem implant uchun\n"
        "rasm: https://...</code>",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text.strip()

    # 1. MANUAL REJIM
    if any(text.lower().startswith(k) for k in ["nom:", "name:", "mahsulot:"]):
        processing_msg = await message.answer("✍️ Ma'lumotlar o'qilmoqda...")
        product_data = parse_manual_input(text)
        if not product_data:
            await bot.edit_message_text(
                "⚠️ Format noto'g'ri.\n\nQuyidagicha yozing:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000\ntavsif: Tavsif</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return
        await bot.edit_message_text("🤖 AI kartochka tayyorlamoqda...", chat_id=message.chat.id, message_id=processing_msg.message_id)
        card_text = await make_card(product_data)
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await send_card(message, product_data, card_text)
        return

    # 2. HAVOLA REJIM
    url = extract_url(text)
    if not url:
        await message.answer(
            "⚠️ Havola yoki ma'lumot topilmadi.\n\n"
            "📎 AliExpress yoki 1688 havolasini yuboring\n\n"
            "✍️ Yoki qo'lda yozing:\n"
            "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
            parse_mode="HTML"
        )
        return

    if not is_aliexpress_link(url):
        processing_msg = await message.answer("🔍 Havola tekshirilmoqda...")
        resolved = await resolve_short_url(url)
        if not is_aliexpress_link(resolved):
            await bot.edit_message_text(
                "⚠️ Faqat <b>AliExpress</b> va <b>1688</b> havolalarini qabul qilaman.",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return
        url = resolved
    else:
        processing_msg = await message.answer("⏳ Mahsulot yuklanmoqda...")

    try:
        if any(d in url for d in ["ali.click", "alx.click"]):
            await bot.edit_message_text("🔗 Havola ochilmoqda...", chat_id=message.chat.id, message_id=processing_msg.message_id)
            url = await resolve_short_url(url)

        await bot.edit_message_text("🔍 Sahifa o'qilmoqda...", chat_id=message.chat.id, message_id=processing_msg.message_id)
        product_data = await scrape_aliexpress(url)

        if not product_data:
            await bot.edit_message_text(
                "❌ Ma'lumot olishda xatolik.\n\nQo'lda kiritib ko'ring:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return

        await bot.edit_message_text("🤖 AI kartochka tayyorlamoqda...", chat_id=message.chat.id, message_id=processing_msg.message_id)
        card_text = await make_card(product_data)
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await send_card(message, product_data, card_text)

    except Exception as e:
        logger.error(f"Xatolik: {e}")
        try:
            await bot.edit_message_text(f"❌ Xatolik: {str(e)[:200]}", chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            await message.answer(f"❌ Xatolik: {str(e)[:200]}")

@dp.callback_query(F.data.startswith("upload:"))
async def callback_upload(call: CallbackQuery):
    product_id = call.data.split(":")[1]
    product_data = product_cache.get(product_id)
    if not product_data:
        await call.answer("⚠️ Ma'lumot topilmadi. Qayta yuboring.", show_alert=True)
        return
    await call.answer("⏳ Yuklanmoqda...")
    await call.message.edit_text("⏳ XazDentga yuklanmoqda...")
    result = await upload_to_xazdent(product_data)
    if result.get("ok"):
        article = result.get("article_code", "")
        pid = result.get("product_id", "")
        await call.message.edit_text(
            f"✅ <b>XazDentga yuklandi!</b>\n\n"
            f"🔢 Artikul: <code>{article}</code>\n"
            f"🆔 Mahsulot ID: <code>{pid}</code>\n\n"
            f"🌍 @XazdentBot katalogida ko'rinadi",
            parse_mode="HTML"
        )
        product_cache.pop(product_id, None)
    else:
        error = result.get("error", "Noma'lum xatolik")
        await call.message.edit_text(f"❌ Yuklashda xatolik:\n<code>{error}</code>\n\nQayta urinib ko'ring.", parse_mode="HTML")

async def main():
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
