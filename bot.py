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
from ai_processor import make_card, make_card_from_post, make_card_from_image
from xazdent_uploader import upload_to_xazdent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class NarxState(StatesGroup):
    kutish = State()

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
    photos = product_data.get("images", [])
    if photos:
        media = []
        for i, url in enumerate(photos[:8]):
            if i == 0:
                media.append(InputMediaPhoto(media=url, caption=card_text, parse_mode="HTML"))
            else:
                media.append(InputMediaPhoto(media=url))
        try:
            await message.answer_media_group(media)
            return
        except:
            pass
    await message.answer(card_text, parse_mode="HTML")

async def ask_price(message: Message, product_data: dict, state: FSMContext,
                    currency: str = "so'm"):
    product_id = product_data.get("product_id", "")
    price_uzs  = product_data.get("price_uzs", 0)
    product_cache[product_id] = product_data

    if price_uzs and price_uzs > 0:
        currency_note = ""
        if product_data.get("price_currency") == "noaniq":
            currency_note = "\n⚠️ <i>Valyuta noaniq — so'mga aylantiring</i>"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, to'g'ri", callback_data=f"price_ok:{product_id}"),
            InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"price_change:{product_id}"),
        ]])
        await message.answer(
            f"💰 <b>Topilgan narx:</b> {format_price(price_uzs)} so'm"
            f"{currency_note}\n\nBu narx to'g'rimi?",
            reply_markup=keyboard, parse_mode="HTML"
        )
    else:
        await state.set_state(NarxState.kutish)
        await state.update_data(product_id=product_id)
        await message.answer(
            "💰 <b>Narxni kiriting</b> (so'mda):\n"
            "<i>Masalan: 850000</i>",
            parse_mode="HTML"
        )

async def do_upload(target, product_data: dict, is_callback: bool = False):
    if is_callback:
        await target.message.edit_text("⏳ XazDentga yuklanmoqda...")
    else:
        msg = await target.answer("⏳ XazDentga yuklanmoqda...")

    result = await upload_to_xazdent(product_data, bot=bot)

    text = (
        f"✅ <b>XazDentga yuklandi!</b>\n\n"
        f"🔢 Artikul: <code>{result.get('article_code', '')}</code>\n"
        f"🆔 ID: <code>{result.get('product_id', '')}</code>\n"
        f"💰 Narx: {format_price(product_data.get('price_uzs', 0))} so'm\n\n"
        f"🌍 @XazdentBot katalogida ko'rinadi"
    ) if result.get("ok") else (
        f"❌ Yuklashda xatolik:\n"
        f"<code>{result.get('error', 'Noma\'lum xatolik')}</code>\n\n"
        f"Qayta urinib ko'ring."
    )

    if is_callback:
        await target.message.edit_text(text, parse_mode="HTML")
    else:
        await msg.edit_text(text, parse_mode="HTML")

    product_cache.pop(product_data.get("product_id", ""), None)


# ============================================================
# START
# ============================================================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Salom! Men <b>XazDent Hamkor Bot</b>man.\n\n"
        "Mahsulot qo'shish usullari:\n\n"
        "🖼 <b>Rasm yuborish</b> — bot rasmdan o'qiydi\n\n"
        "📎 <b>Havola:</b> AliExpress yoki 1688\n\n"
        "📢 <b>Kanal post forward</b> qiling\n\n"
        "✍️ <b>Qo'lda:</b>\n"
        "<code>nom: Dental turbina\n"
        "narx: 850000\n"
        "tavsif: Tavsif matni</code>",
        parse_mode="HTML"
    )


# ============================================================
# RASM — Vision AI
# ============================================================
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Foydalanuvchi rasm yuborsa — AI rasmdan o'qiydi"""

    processing_msg = await message.answer("🔍 Rasm tahlil qilinmoqda...")

    try:
        # Eng yuqori sifatli rasmni olamiz
        best_photo = message.photo[-1]
        file_id    = best_photo.file_id

        # Rasmni yuklab olamiz
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_bytes = file_bytes.read()

        await bot.edit_message_text(
            "🤖 AI rasmdan ma'lumot ajratmoqda...",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )

        product_data = await make_card_from_image(image_bytes, "photo.jpg")

        # Xatolik bo'ldimi
        if not product_data:
            await bot.edit_message_text(
                "❌ Rasmdan ma'lumot ajratib bo'lmadi.\n\n"
                "Qo'lda kiriting:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                parse_mode="HTML"
            )
            return

        # Xatolik xabari
        if product_data.get("_error"):
            await bot.edit_message_text(
                f"❌ AI xatolik:\n<code>{product_data['_error'][:300]}</code>\n\n"
                "Qo'lda kiriting:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                parse_mode="HTML"
            )
            return

        if product_data.get("_not_dental"):
            await bot.edit_message_text(
                "⚠️ Bu stomatologiya mahsuloti emas.\n\n"
                "Faqat dental mahsulot rasmlari qabul qilinadi.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            return

        # Rasmning file_id ni saqlaymiz
        product_data["photo_file_ids"] = [file_id]

        await bot.delete_message(
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )

        card_text = product_data.get("card_text", "")

        # Boshqa do'kon logosi bor — ogohlantirish
        if product_data.get("has_other_shop_logo"):
            shop_name = product_data.get("shop_name", "boshqa do'kon")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Davom etish",
                    callback_data=f"logo_ok:{product_data['product_id']}"
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="logo_cancel"
                ),
            ]])
            product_cache[product_data["product_id"]] = product_data
            await message.answer_photo(
                photo=file_id,
                caption=card_text,
                parse_mode="HTML"
            )
            await message.answer(
                f"⚠️ <b>Diqqat!</b>\n\n"
                f"Rasmda <b>{shop_name}</b> logosi bor.\n"
                f"Bu rasmni o'z do'koningizga yuklashni tasdiqlaysizmi?",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

        # Oddiy holat — kartochka + narx so'rash
        await message.answer_photo(
            photo=file_id,
            caption=card_text,
            parse_mode="HTML"
        )
        await ask_price(message, product_data, state)

    except Exception as e:
        logger.error(f"Rasm xatolik: {e}")
        try:
            await bot.edit_message_text(
                f"❌ Xatolik: {str(e)[:200]}",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
        except:
            await message.answer(f"❌ Xatolik: {str(e)[:200]}")


# ============================================================
# LOGO OGOHLANTIRISH CALLBACK
# ============================================================
@dp.callback_query(F.data.startswith("logo_ok:"))
async def callback_logo_ok(call: CallbackQuery, state: FSMContext):
    product_id   = call.data.split(":")[1]
    product_data = product_cache.get(product_id)
    if not product_data:
        await call.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    await call.answer()
    await call.message.delete()
    await ask_price(call.message, product_data, state)

@dp.callback_query(F.data == "logo_cancel")
async def callback_logo_cancel(call: CallbackQuery):
    await call.answer("Bekor qilindi")
    await call.message.edit_text("❌ Yuklash bekor qilindi.")


# ============================================================
# TELEGRAM FORWARD
# ============================================================
@dp.message(F.forward_origin)
async def handle_forward(message: Message, state: FSMContext):
    processing_msg = await message.answer("📢 Kanal posti o'qilmoqda...")
    post_text = message.caption or message.text or ""
    photos    = []
    if message.photo:
        photos = [message.photo[-1].file_id]

    if not post_text and not photos:
        await bot.edit_message_text(
            "⚠️ Post da matn yoki rasm topilmadi.",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        return

    await bot.edit_message_text(
        "🤖 AI matnni tahlil qilmoqda...",
        chat_id=message.chat.id,
        message_id=processing_msg.message_id
    )

    product_data = await make_card_from_post({"text": post_text, "photo_file_ids": photos})
    await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

    if not product_data:
        await message.answer(
            "❌ Postdan ma'lumot ajratib bo'lmadi.\n\n"
            "Qo'lda kiriting:\n"
            "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
            parse_mode="HTML"
        )
        return

    card_text = product_data.get("card_text", "")
    await message.answer(card_text, parse_mode="HTML")
    await ask_price(message, product_data, state)


# ============================================================
# NARX HOLATI
# ============================================================
@dp.message(NarxState.kutish)
async def handle_narx_input(message: Message, state: FSMContext):
    import re
    digits = re.sub(r"[^\d]", "", message.text.strip())
    if not digits:
        await message.answer("⚠️ Faqat raqam yozing.\n<i>Masalan: 850000</i>", parse_mode="HTML")
        return

    price_uzs    = int(digits)
    data         = await state.get_data()
    product_id   = data.get("product_id", "")
    product_data = product_cache.get(product_id)

    if not product_data:
        await state.clear()
        await message.answer("⚠️ Ma'lumot topilmadi. Qayta yuboring.")
        return

    product_data["price_uzs"] = price_uzs
    product_data["price_usd"] = round(price_uzs / 12800, 2)
    product_cache[product_id] = product_data

    await state.clear()
    await message.answer(f"✅ Narx: <b>{format_price(price_uzs)} so'm</b>", parse_mode="HTML")
    await do_upload(message, product_data)


@dp.callback_query(F.data.startswith("price_ok:"))
async def callback_price_ok(call: CallbackQuery):
    product_id   = call.data.split(":")[1]
    product_data = product_cache.get(product_id)
    if not product_data:
        await call.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    await call.answer("✅ Tasdiqlandi")
    await do_upload(call, product_data, is_callback=True)

@dp.callback_query(F.data.startswith("price_change:"))
async def callback_price_change(call: CallbackQuery, state: FSMContext):
    product_id = call.data.split(":")[1]
    if product_id not in product_cache:
        await call.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.set_state(NarxState.kutish)
    await state.update_data(product_id=product_id)
    await call.message.edit_text(
        "✏️ Yangi narxni so'mda yozing:\n<i>Masalan: 850000</i>",
        parse_mode="HTML"
    )


# ============================================================
# MATN VA HAVOLA
# ============================================================
@dp.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    text = message.text.strip()

    # Manual rejim
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
        product_data["card_text"] = card_text
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await send_card_with_photos(message, product_data, card_text)
        await ask_price(message, product_data, state)
        return

    # Havola rejim
    url = extract_url(text)
    if not url:
        await message.answer(
            "⚠️ Nimani yubormoqchisiz?\n\n"
            "🖼 Rasm yuborish\n"
            "📎 AliExpress/1688 havolasi\n"
            "📢 Kanal postini forward qilish\n"
            "✍️ Qo'lda: <code>nom: ...\nnarx: ...</code>",
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
        product_data["card_text"] = card_text
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        await send_card_with_photos(message, product_data, card_text)
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
