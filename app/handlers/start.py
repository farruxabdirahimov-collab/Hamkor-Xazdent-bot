# -*- coding: utf-8 -*-
"""Sotuvchi bot — start, onboarding (ro'yxatdan o'tish) va asosiy menyu.

Sotuvchi bot xaridor botdan ALOHIDA, lekin BIR XIL bazadan foydalanadi.
Bu yerda hamma "sotuvchi" sifatida ishlaydi: /start → do'kon bo'lsa menyu,
bo'lmasa qisqa onboarding (ism → telefon → viloyat → shartlar → do'kon).
"""
import logging
from aiogram import F
from aiogram.types import (
    Message, CallbackQuery, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from app.runtime import bot, dp, router
from app.config import ADMIN_IDS, WEBAPP_URL
from app.database import get_user, db_run, db_get, db_all, db_insert
from app.texts import REGIONS
from app.keyboards import ik, ib, rk, kb_seller, kb_regions
from app.states import RegState
from app import logger as xlog

log = logging.getLogger(__name__)


async def _ensure_shop(uid, u):
    """Sotuvchi uchun do'kon bo'lmasa yaratamiz (active)."""
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    if not shop:
        sname = (u.get("clinic_name") or u.get("full_name") or "Do'konim") if u else "Do'konim"
        await db_insert(
            "INSERT INTO shops(owner_id,shop_name,category,phone,region,status) "
            "VALUES(?,?,?,?,?,'active')",
            (uid, sname, "Stomatologiya",
             (u.get("phone", "") if u else ""), (u.get("region", "") if u else "")),
        )
        shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    return shop


async def _show_seller_menu(msg, u):
    uid = msg.from_user.id
    lg = (u.get("lang") if u else None) or "uz"
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    sname = (shop["shop_name"] if shop else None) or (u.get("clinic_name") if u else "") or "Do'konim"
    await msg.answer(
        f"🏪 *{sname}*\n📍 {(u.get('region') if u else '') or ''}\n\n"
        f"Sotuvchi paneliga xush kelibsiz! Pastdagi tugmalardan foydalaning 👇",
        reply_markup=kb_seller(lg, uid=uid, webapp_url=WEBAPP_URL),
    )


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    u = await get_user(uid)
    if not u:
        await db_run(
            "INSERT INTO users(id,username,full_name) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",
            (uid, msg.from_user.username, msg.from_user.full_name),
        )
        u = await get_user(uid)
        xlog.notify(
            f"Yangi SOTUVCHI bot foydalanuvchisi:\n{msg.from_user.full_name} "
            f"(@{msg.from_user.username or '—'})\nid={uid}", "NEW",
        )

    # Profil to'liq (xaridor botda ham ro'yxatdan o'tgan bo'lishi mumkin) → menyu
    if u and u.get("phone") and u.get("region"):
        await _ensure_shop(uid, u)
        await _show_seller_menu(msg, u)
        return

    # Aks holda — qisqa onboarding
    await state.set_state(RegState.name)
    await msg.answer(
        "🏪 *XazDent — Sotuvchi paneli*\n\n"
        "Sotuvchi sifatida ro'yxatdan o'tamiz.\n\n"
        "Do'kon nomini yoki ism-familiyangizni kiriting:\n"
        "_Masalan: DentalPlus — yoki — Alisher Karimov_",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(RegState.name)
async def reg_name(msg: Message, state: FSMContext):
    name = (msg.text or "").strip()
    if len(name) < 2:
        await msg.answer("⚠️ Kamida 2 ta harf kiriting.")
        return
    await state.update_data(reg_name=name)
    await state.set_state(RegState.phone)
    await msg.answer(
        "📞 *Telefon raqamingizni yuboring*\n_Xaridorlar siz bilan bog'lanishi uchun_",
        reply_markup=rk(
            [KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)],
            one_time=True,
        ),
    )


@router.message(RegState.phone, F.contact)
async def reg_phone_contact(msg: Message, state: FSMContext):
    await _save_phone(msg, state, msg.contact.phone_number)


@router.message(RegState.phone, F.text)
async def reg_phone_text(msg: Message, state: FSMContext):
    phone = (msg.text or "").strip().replace(" ", "")
    if not (phone.startswith("+998") or phone.startswith("998")) or len(phone.replace("+", "")) < 12:
        await msg.answer("⚠️ Raqamni +998XXXXXXXXX ko'rinishida yuboring yoki tugmani bosing.")
        return
    await _save_phone(msg, state, phone)


async def _save_phone(msg, state, phone):
    await state.update_data(reg_phone=phone)
    await state.set_state(RegState.region)
    await msg.answer(
        "📍 *Viloyatingizni tanlang:*",
        reply_markup=ReplyKeyboardRemove(),
    )
    await msg.answer("👇", reply_markup=kb_regions("uz"))


@router.callback_query(F.data.startswith("reg_"), RegState.region)
async def reg_region(call: CallbackQuery, state: FSMContext):
    try:
        idx = int(call.data[4:])
        region = REGIONS[idx]
    except Exception:
        region = "—"
    await state.update_data(reg_region=region)
    await state.set_state(RegState.terms)
    await call.message.edit_text(
        "📜 *Shartlar*\n\n"
        "• Faqat stomatologiya mahsulotlari\n"
        "• Narx va sifat uchun javobgarlik sotuvchida\n"
        "• Buyurtmalarni o'z vaqtida bajarish\n\n"
        "Davom etish uchun roziligingizni bildiring:",
        reply_markup=ik([ib("✅ Roziman, davom etish", "seller_terms_ok")]),
    )
    await call.answer()


@router.callback_query(F.data == "seller_terms_ok", RegState.terms)
async def reg_terms_ok(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    d = await state.get_data()
    name = d.get("reg_name", "") or call.from_user.full_name or ""
    phone = d.get("reg_phone", "")
    region = d.get("reg_region", "")
    await db_run(
        "UPDATE users SET clinic_name=?, full_name=?, phone=?, region=? WHERE id=?",
        (name, name, phone, region, uid),
    )
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.answer()
    await state.clear()
    u = await get_user(uid)
    await _ensure_shop(uid, u)
    await call.message.answer(
        f"✅ *Do'koningiz ochildi!* 🎉\n\n"
        f"🏪 {name}\n📍 {region}\n\n"
        f"Mahsulotingizni butun O'zbekiston bo'ylab stomatolog va klinikalarga "
        f"yetkazamiz. 📸 Mahsulotni *chiroyli holda bir marta* yuklang — doimiy soting!\n\n"
        f"*Qisqa qo'llanma:*\n"
        f"1️⃣ ➕ Mahsulot qo'shing (chiroyli surat + aniq narx)\n"
        f"2️⃣ 🔔 Buyurtma kelganda xabar olasiz\n"
        f"3️⃣ ✅ Qabul qilib, yetkazib bering\n"
        f"4️⃣ ⭐ Reyting yig'ib, ko'proq soting",
        reply_markup=ik([ib("📖 To'liq qo'llanma", "seller_guide")]),
    )
    await _show_seller_menu(call.message if hasattr(call, "message") else call, u)
    # Adminlarga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"🆕 *Yangi sotuvchi (sotuvchi bot)*\n\n"
                f"🏪 {name}\n📞 {phone}\n📍 {region}\n🆔 `{uid}`",
            )
        except Exception:
            pass


# ── Menyu: Buyurtmalar / Yordam ──────────────────────────────────────────────
@router.message(F.text == "🔔 Buyurtmalar")
async def seller_orders(msg: Message):
    uid = msg.from_user.id
    rows = await db_all(
        "SELECT * FROM orders WHERE seller_id=? "
        "AND status IN ('new','accepted','preparing','shipped') "
        "ORDER BY created_at DESC LIMIT 20",
        (uid,),
    )
    if not rows:
        await msg.answer("📭 Hozircha faol buyurtma yo'q.")
        return
    st_map = {"new": "🆕 Yangi", "accepted": "✅ Qabul qilingan",
              "preparing": "📦 Tayyorlanmoqda", "shipped": "🚚 Yo'lda"}
    await msg.answer(f"🔔 *Faol buyurtmalar:* {len(rows)} ta")
    for o in rows:
        total = float(o.get("total_amount") or 0)
        await msg.answer(
            f"{st_map.get(o['status'], o['status'])} — *{o.get('order_number') or ('#'+str(o['id']))}*\n"
            f"💰 {total:,.0f} so'm"
        )


@router.message(F.text == "📖 Yordam")
async def seller_help(msg: Message):
    await msg.answer(
        "📖 *Yordam — Sotuvchi paneli*\n\n"
        "🛍 *Dental Market* — katalog va do'koningiz\n"
        "➕ *Mahsulot qo'shish* — yangi mahsulot (rasm/havola ham yuborsangiz bo'ladi)\n"
        "🔔 *Buyurtmalar* — faol buyurtmalaringiz\n"
        "💰 *Hisobim* — balans va to'ldirish\n"
        "⚙️ *Profil* — ma'lumotlaringiz\n\n"
        "Savol bo'lsa adminlarga murojaat qiling.",
        reply_markup=ik([ib("📖 To'liq qo'llanma", "seller_guide")]),
    )


@router.callback_query(F.data == "seller_guide")
async def cb_seller_guide(call: CallbackQuery):
    await call.message.answer(
        "📖 *To'liq qo'llanma — qanday sotish kerak*\n\n"
        "*1. Mahsulot qo'shish*\n"
        "➕ \"Mahsulot qo'shish\" → nom, narx, miqdor. *Chiroyli, aniq surat* yuklang — "
        "xaridor avval rasmni ko'radi. Narxni to'g'ri kiriting.\n\n"
        "*2. Buyurtma*\n"
        "🔔 Xaridor buyurtma bersa, sizga shu bot orqali xabar keladi: mahsulot, miqdor, "
        "manzil, telefon. Tez *qabul qiling* yoki *rad eting*.\n\n"
        "*3. Yetkazish*\n"
        "✅ Qabul → 📦 Tayyorlash → 🚚 Jo'natish → ✅ Yetkazildi. Har bosqichda xaridor xabardor bo'ladi.\n\n"
        "*4. Reyting*\n"
        "⭐ O'z vaqtida yetkazsangiz yaxshi reyting olasiz — ko'proq buyurtma keladi.\n\n"
        "💡 *Maslahat:* mahsulotni bir marta sifatli yuklang — u doimiy ko'rinib turadi va sotiladi.",
    )
    await call.answer()

