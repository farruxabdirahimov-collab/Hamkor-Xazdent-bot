import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from scraper import scrape_aliexpress, parse_manual_input
from ai_processor import make_card
from xazdent_uploader import upload_to_xazdent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Narx kutish holati
class NarxState(StatesGroup):
    kutish = State()

# Vaqtincha xotira
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

def format_price(price_uzs: int) -> str:
    """Narxni chiroyli ko'rsatish: 1250000 → 1,250,000"""
    return f"{price_uzs:,}".replace(",", " ")

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

async def send_card_with_photos(message: Message, product_data: dict, card_text: str):
    """Faqat kartochka va rasmlarni yuboradi — narx so'rovi alohida"""
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

async def ask_price(message: Message, product_data: dict, state: FSMContext):
    """Narxni tasdiqlash yoki yangi narx so'rash"""
    product_id = product_data.get("product_id", "")
    price_uzs = product_data.get("price_uzs", 0)

    # Keshga saqlash
    product_cache[product_id] = product_data

    if price_uzs and price_uzs > 0:
        # Narx topilgan — tasdiqlashni so'raymiz
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, to'g'ri", callback_data=f"price_ok:{product_id}"),
                InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"price_change:{product_id}"),
            ]
        ])
        await message.answer(
            f"💰 <b>Topilgan narx:</b> {format_price(price_uzs)} so'm\n\n"
            f"Bu narx to'g'rimi?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        # Narx topilmadi — so'raymiz
        await state.set_state(NarxState.kutish)
        await state.update_data(product_id=product_id)
        await message.answer(
            "💰 <b>Narx topilmadi.</b>\n\n"
            "Mahsulot narxini so'mda yozing:\n"
            "<i>Masalan: 850000</i>",
            parse_mode="HTML"
        )

async def do_upload(message_or_call, product_data: dict, is_callback: bool = False):
    """XazDentga yuklash"""
    if is_callback:
        await message_or_call.message.edit_text("⏳ XazDentga yuklanmoqda...")
    else:
        msg = await message_or_call.answer("⏳ XazDentga yuklanmoqda...")

    result = await upload_to_xazdent(product_data)

    success_text = (
        f"✅ <b>XazDentga yuklandi!</b>\n\n"
        f"🔢 Artikul: <code>{result.get('article_code', '')}</code>\n"
        f"🆔 Mahsulot ID: <code>{result.get('product_id', '')}</code>\n"
        f"💰 Narx: {format_price(product_data.get('price_uzs', 0))} so'm\n\n"
        f"🌍 @XazdentBot katalogida ko'rinadi"
    )
    error_text = (
        f"❌ Yuklashda xatolik:\n"
        f"<code>{result.get('error', 'Noma\'lum xatolik')}</code>\n\n"
        f"Qayta urinib ko'ring."
    )

    if is_callback:
        await message_or_call.message.edit_text(
            success_text if result.get("ok") else error_text,
            parse_mode="HTML"
        )
    else:
        await msg.edit_text(
            success_text if result.get("ok") else error_text,
            parse_mode="HTML"
        )

    # Keshdan o'chirish
    product_cache.pop(product_data.get("product_id", ""), None)


# ============================================================
# HANDLERLAR
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Salom! Men <b>XazDent Hamkor Bot</b>man.\n\n"
        "📎 <b>Havola orqali:</b>\n"
        "AliExpress yoki 1688 havolasini yuboring\n\n"
        "✍️ <b>Qo'lda kiritish:</b>\n"
        "<code>nom: Dental turbina\n"
        "narx: 850000\n"
        "tavsif: Osstem implant uchun</code>",
        parse_mode="HTML"
    )

@dp.message(NarxState.kutish)
async def handle_narx_input(message: Message, state: FSMContext):
    """Foydalanuvchi narx yozganda"""
    import re
    text = message.text.strip()
    digits = re.sub(r"[^\d]", "", text)

    if not digits:
        await message.answer(
            "⚠️ Faqat raqam yozing.\n"
            "<i>Masalan: 850000</i>",
            parse_mode="HTML"
        )
        return

    price_uzs = int(digits)
    data = await state.get_data()
    product_id = data.get("product_id", "")
    product_data = product_cache.get(product_id)

    if not product_data:
        await state.clear()
        await message.answer("⚠️ Ma'lumot topilmadi. Havolani qayta yuboring.")
        return

    # Narxni yangilaymiz
    product_data["price_uzs"] = price_uzs
    product_data["price_usd"] = round(price_uzs / 12800, 2)
    product_cache[product_id] = product_data

    await state.clear()
    await message.answer(f"✅ Narx qabul qilindi: <b>{format_price(price_uzs)} so'm</b>", parse_mode="HTML")
    await do_upload(message, product_data)


@dp.callback_query(F.data.startswith("price_ok:"))
async def callback_price_ok(call: CallbackQuery):
    """Narx tasdiqlandi — yuklaymiz"""
    product_id = call.data.split(":")[1]
    product_data = product_cache.get(product_id)
    if not product_data:
        await call.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    await call.answer("✅ Narx tasdiqlandi")
    await do_upload(call, product_data, is_callback=True)


@dp.callback_query(F.data.startswith("price_change:"))
async def callback_price_change(call: CallbackQuery, state: FSMContext):
    """Narxni o'zgartirish"""
    product_id = call.data.split(":")[1]
    if product_id not in product_cache:
        await call.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.set_state(NarxState.kutish)
    await state.update_data(product_id=product_id)
    await call.message.edit_text(
        "✏️ Yangi narxni so'mda yozing:\n"
        "<i>Masalan: 850000</i>",
        parse_mode="HTML"
    )


@dp.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    text = message.text.strip()

    # 1. MANUAL REJIM
    if any(text.lower().startswith(k) for k in ["nom:", "name:", "mahsulot:"]):
        processing_msg = await message.answer("✍️ Ma'lumotlar o'qilmoqda...")
        product_data = parse_manual_input(text)
        if not product_data:
            await bot.edit_message_text(
                "⚠️ Format noto'g'ri.\n\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000\ntavsif: Tavsif</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return
        await bot.edit_message_text("🤖 AI kartochka tayyorlamoqda...",
            chat_id=message.chat.id, message_id=processing_msg.message_id)
        card_text = await make_card(product_data)
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await send_card_with_photos(message, product_data, card_text)
        await ask_price(message, product_data, state)
        return

    # 2. HAVOLA REJIM
    url = extract_url(text)
    if not url:
        await message.answer(
            "⚠️ Havola yoki ma'lumot topilmadi.\n\n"
            "📎 AliExpress yoki 1688 havolasini yuboring\n\n"
            "✍️ Yoki qo'lda:\n"
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
            await bot.edit_message_text("🔗 Havola ochilmoqda...",
                chat_id=message.chat.id, message_id=processing_msg.message_id)
            url = await resolve_short_url(url)

        await bot.edit_message_text("🔍 Sahifa o'qilmoqda...",
            chat_id=message.chat.id, message_id=processing_msg.message_id)
        product_data = await scrape_aliexpress(url)

        if not product_data:
            await bot.edit_message_text(
                "❌ Ma'lumot olishda xatolik.\n\nQo'lda kiritib ko'ring:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return

        await bot.edit_message_text("🤖 AI kartochka tayyorlamoqda...",
            chat_id=message.chat.id, message_id=processing_msg.message_id)
        card_text = await make_card(product_data)
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

        # Kartochka yuborish
        await send_card_with_photos(message, product_data, card_text)

        # Narx so'rash
        await ask_price(message, product_data, state)

    except Exception as e:
        logger.error(f"Xatolik: {e}")
        try:
            await bot.edit_message_text(f"❌ Xatolik: {str(e)[:200]}",
                chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            await message.answer(f"❌ Xatolik: {str(e)[:200]}")


async def main():
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
