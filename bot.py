import asyncio
import logging
import os
import json
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.filters import CommandStart, Command
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

# Admin Telegram ID — Railway Variables da ADMIN_ID qo'shing
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0"))
XAZDENT_API_URL = os.getenv("XAZDENT_API_URL", "")
PARTNER_TOKEN   = os.getenv("PARTNER_TOKEN", "")

# Vaqtincha xotira
product_cache = {}
# Sessiya: uid → seller ma'lumoti (RAM da, restart bo'lsa o'chadi)
seller_sessions = {}

class NarxState(StatesGroup):
    kutish = State()

ALIEXPRESS_DOMAINS = [
    "aliexpress.com", "aliexpress.ru", "a.aliexpress.com",
    "s.click.aliexpress.com", "click.aliexpress.com",
    "ali.click", "alx.click", "aliclick.com",
    "1688.com", "detail.1688.com", "s.1688.com",
]

# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

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
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True, ssl=False,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                return str(resp.url)
    except Exception as e:
        logger.error(f"Redirect xatolik: {e}")
        return url

async def check_access(uid: int) -> dict:
    """XazDentdan ruxsatni tekshirish"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XAZDENT_API_URL}/api/partner/check_access",
                params={"uid": uid},
                headers={"X-Partner-Token": PARTNER_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False
            ) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"check_access xatolik: {e}")
        return {"ok": False, "error": str(e)}

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

async def ask_price(message: Message, product_data: dict, state: FSMContext):
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
            "💰 <b>Narxni kiriting</b> (so'mda):\n<i>Masalan: 850000</i>",
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
# START — KIRISH TEKSHIRUVI
# ============================================================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    # Admin — to'g'ridan kiradi
    if is_admin(uid):
        seller_sessions[uid] = {"name": "Admin", "is_admin": True}
        await message.answer(
            "👋 Salom, Admin!\n\n"
            "📦 Mahsulot yuklash yoki /admin — boshqaruv paneli",
            parse_mode="HTML"
        )
        return

    # Tekshirish
    checking = await message.answer("🔍 Tekshirilmoqda...")
    access = await check_access(uid)

    if not access.get("ok"):
        error = access.get("error", "")
        status = access.get("status", "")
        role   = access.get("role", "")

        if status == "blocked":
            text = "🚫 <b>Siz bloklangansiz.</b>\n\nBatafsil: @XazdentSupport"
        elif role and role != "seller":
            text = "⚠️ <b>Bu bot faqat sotuvchilar uchun.</b>\n\n@XazdentBot da sotuvchi sifatida ro'yxatdan o'ting."
        else:
            text = (
                "❌ <b>Ruxsat yo'q.</b>\n\n"
                "Hamkor botdan foydalanish uchun:\n"
                "1. @XazdentBot da sotuvchi bo'ling\n"
                "2. Admin orqali ruxsat so'rang\n\n"
                "📩 @XazdentSupport"
            )
        await bot.edit_message_text(text, chat_id=message.chat.id,
            message_id=checking.message_id, parse_mode="HTML")
        return

    if not access.get("can_upload"):
        remaining = access.get("remaining", 0)
        limit     = access.get("limit", 0)
        await bot.edit_message_text(
            f"⚠️ <b>Limit tugadi.</b>\n\n"
            f"Oylik limit: {limit} ta\n"
            f"Ishlatilgan: {access.get('used', 0)} ta\n"
            f"Qolgan: {remaining} ta\n\n"
            f"Limitni oshirish uchun: @XazdentSupport",
            chat_id=message.chat.id,
            message_id=checking.message_id,
            parse_mode="HTML"
        )
        return

    # Muvaffaqiyatli kirish
    seller_sessions[uid] = access
    name      = access.get("name", "Sotuvchi")
    remaining = access.get("remaining", 0)
    limit     = access.get("limit", 0)

    await bot.edit_message_text(
        f"👋 Salom, <b>{name}</b>!\n\n"
        f"📊 Limit: {limit - remaining}/{limit} ishlatilgan\n"
        f"✅ Qolgan: <b>{remaining} ta</b>\n\n"
        f"Mahsulot qo'shish usullari:\n\n"
        f"🖼 <b>Rasm yuborish</b> — AI rasmdan o'qiydi\n"
        f"📎 <b>Havola:</b> AliExpress yoki 1688\n"
        f"📢 <b>Kanal post</b> — forward qiling\n"
        f"✍️ <b>Qo'lda:</b>\n"
        f"<code>nom: Dental turbina\nnarx: 850000</code>",
        chat_id=message.chat.id,
        message_id=checking.message_id,
        parse_mode="HTML"
    )


# ============================================================
# ADMIN PANEL
# ============================================================
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Sotuvchilar", callback_data="admin_sellers"),
            InlineKeyboardButton(text="📦 Mahsulotlar", callback_data="admin_products"),
        ],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
            InlineKeyboardButton(text="💰 To'lovlar", callback_data="admin_payments"),
        ],
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_refresh"),
        ]
    ])

    await message.answer(
        "⚙️ <b>Hamkor Bot — Admin Panel</b>\n\n"
        "Bo'limni tanlang:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_sellers")
async def admin_sellers(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return

    await call.answer()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XAZDENT_API_URL}/api/admin/partner_sellers",
                headers={"X-Partner-Token": PARTNER_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False
            ) as resp:
                data = await resp.json()

        sellers = data.get("sellers", [])
        if not sellers:
            await call.message.edit_text(
                "👥 <b>Hamkor sotuvchilar</b>\n\nHali hech kim yo'q.",
                parse_mode="HTML"
            )
            return

        text = "👥 <b>Hamkor sotuvchilar:</b>\n\n"
        keyboard_rows = []

        for s in sellers[:10]:
            status_icon = "✅" if s.get("status") == "active" else "🚫"
            name    = s.get("name", "Noma'lum")
            used    = s.get("used", 0)
            limit   = s.get("limit", 0)
            uid     = s.get("uid", 0)
            text   += f"{status_icon} <b>{name}</b> — {used}/{limit} ta\n"
            keyboard_rows.append([
                InlineKeyboardButton(
                    text=f"{'🚫 Bloklash' if s.get('status') == 'active' else '✅ Ochish'} — {name[:15]}",
                    callback_data=f"toggle_seller:{uid}"
                )
            ])

        keyboard_rows.append([
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_back")
        ])

        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            parse_mode="HTML"
        )

    except Exception as e:
        await call.message.edit_text(f"❌ Xatolik: {str(e)[:200]}", parse_mode="HTML")

@dp.callback_query(F.data.startswith("toggle_seller:"))
async def toggle_seller(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return

    uid = int(call.data.split(":")[1])
    await call.answer("⏳ O'zgartirilmoqda...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XAZDENT_API_URL}/api/admin/partner_toggle",
                json={"uid": uid},
                headers={
                    "X-Partner-Token": PARTNER_TOKEN,
                    "Content-Type": "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False
            ) as resp:
                result = await resp.json()

        if result.get("ok"):
            new_status = result.get("status", "")
            icon = "✅" if new_status == "active" else "🚫"
            await call.answer(f"{icon} Holat o'zgartirildi", show_alert=True)
            await admin_sellers(call)
        else:
            await call.answer(f"❌ Xatolik: {result.get('error', '')}", show_alert=True)

    except Exception as e:
        await call.answer(f"❌ {str(e)[:100]}", show_alert=True)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return
    await call.answer()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XAZDENT_API_URL}/api/admin/partner_stats",
                headers={"X-Partner-Token": PARTNER_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False
            ) as resp:
                data = await resp.json()

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_back")
        ]])

        await call.message.edit_text(
            f"📊 <b>Statistika:</b>\n\n"
            f"👥 Jami hamkor sotuvchilar: <b>{data.get('total_sellers', 0)}</b>\n"
            f"✅ Aktiv: <b>{data.get('active_sellers', 0)}</b>\n"
            f"📦 Jami yuklangan: <b>{data.get('total_products', 0)}</b>\n"
            f"📅 Bugun: <b>{data.get('today_products', 0)}</b>\n"
            f"📅 Bu oy: <b>{data.get('month_products', 0)}</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        await call.message.edit_text(f"❌ Xatolik: {str(e)[:200]}", parse_mode="HTML")

@dp.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Sotuvchilar", callback_data="admin_sellers"),
            InlineKeyboardButton(text="📦 Mahsulotlar", callback_data="admin_products"),
        ],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
            InlineKeyboardButton(text="💰 To'lovlar", callback_data="admin_payments"),
        ],
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_refresh"),
        ]
    ])
    await call.message.edit_text(
        "⚙️ <b>Hamkor Bot — Admin Panel</b>\n\nBo'limni tanlang:",
        reply_markup=keyboard, parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_products")
async def admin_products(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(
        "📦 <b>So'nggi yuklangan mahsulotlar</b>\n\n"
        "Bu bo'lim @XazdentBot admin panelida to'liq ko'rinadi.\n\n"
        "👉 @XazdentBot → Admin → Market",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_back")
        ]]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_payments")
async def admin_payments(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(
        "💰 <b>To'lovlar</b>\n\n"
        "Hozircha qo'lda boshqariladi.\n"
        "To'lov qilgan sotuvchiga XazDent admin panelidan limit bering.\n\n"
        "👉 @XazdentBot → Admin → 🤝 Hamkor",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_back")
        ]]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_refresh")
async def admin_refresh(call: CallbackQuery):
    await admin_back(call)


# ============================================================
# RASM — Vision AI
# ============================================================
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    uid = message.from_user.id

    if not is_admin(uid) and uid not in seller_sessions:
        await message.answer(
            "⛔ Avval /start bosing va ruxsatni tekshiring."
        )
        return

    processing_msg = await message.answer("🔍 Rasm tahlil qilinmoqda...")
    try:
        best_photo  = message.photo[-1]
        file_id     = best_photo.file_id
        file        = await bot.get_file(file_id)
        file_bytes  = await bot.download_file(file.file_path)
        image_bytes = file_bytes.read()

        await bot.edit_message_text("🤖 AI rasmdan ma'lumot ajratmoqda...",
            chat_id=message.chat.id, message_id=processing_msg.message_id)

        product_data = await make_card_from_image(image_bytes, "photo.jpg")

        if not product_data:
            await bot.edit_message_text(
                "❌ Rasmdan ma'lumot ajratib bo'lmadi.\n\nQo'lda kiriting:\n"
                "<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return

        if product_data.get("_not_dental"):
            await bot.edit_message_text(
                "⚠️ Bu stomatologiya mahsuloti emas.",
                chat_id=message.chat.id, message_id=processing_msg.message_id
            )
            return

        if product_data.get("_error"):
            await bot.edit_message_text(
                f"❌ AI xatolik:\n<code>{product_data['_error'][:200]}</code>\n\n"
                "Qo'lda kiriting:\n<code>nom: Mahsulot nomi\nnarx: 850000</code>",
                chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="HTML"
            )
            return

        product_data["photo_file_ids"] = [file_id]
        await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

        card_text = product_data.get("card_text", "")

        if product_data.get("has_other_shop_logo"):
            shop_name = product_data.get("shop_name", "boshqa do'kon")
            product_cache[product_data["product_id"]] = product_data
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Davom etish", callback_data=f"logo_ok:{product_data['product_id']}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="logo_cancel"),
            ]])
            await message.answer_photo(photo=file_id, caption=card_text, parse_mode="HTML")
            await message.answer(
                f"⚠️ <b>Diqqat!</b>\nRasmda <b>{shop_name}</b> logosi bor.\nDavom etasizmi?",
                reply_markup=keyboard, parse_mode="HTML"
            )
            return

        await message.answer_photo(photo=file_id, caption=card_text, parse_mode="HTML")
        await ask_price(message, product_data, state)

    except Exception as e:
        logger.error(f"Rasm xatolik: {e}")
        try:
            await bot.edit_message_text(f"❌ Xatolik: {str(e)[:200]}",
                chat_id=message.chat.id, message_id=processing_msg.message_id)
        except:
            await message.answer(f"❌ Xatolik: {str(e)[:200]}")


# ============================================================
# LOGO CALLBACK
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
# FORWARD
# ============================================================
@dp.message(F.forward_origin)
async def handle_forward(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_admin(uid) and uid not in seller_sessions:
        await message.answer("⛔ Avval /start bosing.")
        return

    processing_msg = await message.answer("📢 Kanal posti o'qilmoqda...")
    post_text = message.caption or message.text or ""
    photos    = [message.photo[-1].file_id] if message.photo else []

    if not post_text and not photos:
        await bot.edit_message_text("⚠️ Post da matn yoki rasm topilmadi.",
            chat_id=message.chat.id, message_id=processing_msg.message_id)
        return

    await bot.edit_message_text("🤖 AI tahlil qilmoqda...",
        chat_id=message.chat.id, message_id=processing_msg.message_id)

    product_data = await make_card_from_post({"text": post_text, "photo_file_ids": photos})
    await bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

    if not product_data:
        await message.answer(
            "❌ Postdan ma'lumot ajratib bo'lmadi.\n\nQo'lda kiriting:\n"
            "<code>nom: Mahsulot nomi\nnarx: 850000</code>", parse_mode="HTML"
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
        "✏️ Yangi narxni so'mda yozing:\n<i>Masalan: 850000</i>", parse_mode="HTML"
    )


# ============================================================
# MATN VA HAVOLA
# ============================================================
@dp.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    uid  = message.from_user.id
    text = message.text.strip()

    # Admin buyruqlarini o'tkazib yuborish
    if text.startswith("/"):
        return

    # Ruxsat tekshirish
    if not is_admin(uid) and uid not in seller_sessions:
        await message.answer("⛔ Avval /start bosing va ruxsatni tekshiring.")
        return

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
