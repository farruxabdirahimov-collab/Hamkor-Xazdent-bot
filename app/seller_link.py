# -*- coding: utf-8 -*-
"""🔗 Sotuvchi panelini Hamkor botga ulash (telefon raqami orqali).

## Nega kerak

Sotuvchilar endi panelga login/parol bilan kirishadi. Lekin buyurtma
xabari va «✅ Buyurtmani qabul qildim» tugmasi SHU BOTDA keladi. Agar
sotuvchi botni hech qachon ochmagan bo'lsa, buyurtma unga umuman
yetmaydi.

## Qanday ishlaydi

1. Panelda «Telegram botni ulash» bosiladi → backend bir martalik kod
   yozadi (`seller_tg_link` jadvali) va `t.me/<bot>?start=slink_<kod>`
   havolasini beradi.
2. Sotuvchi shu havolani ochadi → bu modul kodni SHU Telegram
   akkauntiga biriktiradi va «Kontaktni yuborish» tugmasini beradi.
3. Sotuvchi raqamini yuboradi. Telegram bergan raqam — TASDIQLANGAN
   (foydalanuvchi qo'lda yoza olmaydi). Uni paneldagi SMS bilan
   tasdiqlangan raqam bilan solishtiramiz.
4. Bir xil bo'lsa — `auth_identities` ga yoziladi. Aks holda RAD.

🔒 `contact.user_id != from_user.id` bo'lsa rad etamiz: Telegram
BOSHQA odamning kontaktini yuborishga ham ruxsat beradi.
"""
import logging
import time as _time

from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandStart
from aiogram.types import (KeyboardButton, Message, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)

from app.database import db_all, db_get, db_run, get_user
from app.runtime import bot, router

log = logging.getLogger(__name__)

LINK_TTL = 900          # bog'lash kodi amal qilish muddati (15 daqiqa)


def _raqam(p):
    """→ '998XXXXXXXXX' yoki None (backend `_norm_phone` bilan bir xil)."""
    d = "".join(c for c in str(p or "") if c.isdigit())
    if d.startswith("998"):
        d = d[3:]
    if len(d) != 9:
        return None
    return "998" + d


def _kontakt_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamimni yuborish",
                                  request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
        input_field_placeholder="Pastdagi tugmani bosing")


async def _jadval():
    await db_run("CREATE TABLE IF NOT EXISTS seller_tg_link("
                 "code TEXT PRIMARY KEY, uid BIGINT, tg_id BIGINT, "
                 "created_at BIGINT)")


# ── /start slink_<kod> ───────────────────────────────────────────────────
# ⚠️ Bu handler `handlers/start.py` dagi `cmd_start` dan OLDIN ro'yxatga
# olinishi SHART (`app/handlers/__init__.py` da birinchi import).
@router.message(CommandStart(), F.text.contains("slink_"))
async def slink_start(msg: Message):
    matn = msg.text or ""
    arg = matn.split(maxsplit=1)[1].strip() if " " in matn else ""
    if not arg.startswith("slink_"):
        raise SkipHandler
    kod = arg[6:].strip()
    tgid = int(msg.from_user.id)

    await _jadval()
    row = await db_get("SELECT uid, created_at FROM seller_tg_link WHERE code=?",
                       (kod,))
    if not row or (int(_time.time()) - int(row["created_at"] or 0)) > LINK_TTL:
        await msg.answer(
            "❌ Ulash havolasi eskirgan.\n\n"
            "Sotuvchi panelida «Telegram botni ulash» tugmasini qayta bosing.",
            reply_markup=ReplyKeyboardRemove())
        return

    await db_run("UPDATE seller_tg_link SET tg_id=? WHERE code=?", (tgid, kod))
    u = await get_user(int(row["uid"])) or {}
    tel = _raqam(u.get("phone")) or ""
    yashirin = ("+" + tel[:5] + "***" + tel[-2:]) if tel else "—"
    await msg.answer(
        "🤝 *XazDent Hamkor*\n\n"
        "Panel akkauntingizni ulash uchun telefon raqamingizni tasdiqlang.\n\n"
        f"Panelda ro'yxatdan o'tgan raqam: *{yashirin}*\n\n"
        "⚠️ Telegram akkauntingizdagi raqam SHU raqam bilan bir xil "
        "bo'lishi shart — aks holda ulanmaydi.",
        reply_markup=_kontakt_kb())


# ── Kontakt ──────────────────────────────────────────────────────────────
# Holat (state) filtri ATAYLAB yo'q: sotuvchi ro'yxatdan o'tish oqimida
# bo'lmasligi mumkin. Kutilayotgan ulash so'rovi bo'lmasa — `SkipHandler`
# bilan keyingi handlerga o'tkazamiz (ro'yxatdan o'tish buzilmaydi).
@router.message(F.contact)
async def slink_kontakt(msg: Message):
    tgid = int(msg.from_user.id)
    await _jadval()
    row = await db_get(
        "SELECT code, uid, created_at FROM seller_tg_link "
        "WHERE tg_id=? ORDER BY created_at DESC LIMIT 1", (tgid,))
    if not row or (int(_time.time()) - int(row["created_at"] or 0)) > LINK_TTL:
        raise SkipHandler          # bizga tegishli emas

    k = msg.contact
    if not k or int(getattr(k, "user_id", 0) or 0) != tgid:
        await msg.answer(
            "❌ Bu sizning raqamingiz emas.\n\n"
            "Pastdagi «📱 Raqamimni yuborish» tugmasini bosing — qo'lda "
            "yozilgan yoki boshqaning kontakti qabul qilinmaydi.",
            reply_markup=_kontakt_kb())
        return

    uid = int(row["uid"])
    u = await get_user(uid) or {}
    panel = _raqam(u.get("phone"))
    kelgan = _raqam(k.phone_number)

    if not panel:
        await msg.answer(
            "❌ Panel akkauntingizda telefon raqami yo'q.\n\n"
            "Avval panelda raqamingizni kiriting, so'ng qayta ulang.",
            reply_markup=ReplyKeyboardRemove())
        return

    if panel != kelgan:
        await msg.answer(
            "❌ *Raqamlar mos kelmadi.*\n\n"
            f"Telegram raqamingiz: `+{kelgan or '—'}`\n"
            f"Paneldagi raqam: `+{panel[:5]}***{panel[-2:]}`\n\n"
            "Panelda va Telegram'da BIR XIL raqam bo'lishi shart.",
            reply_markup=ReplyKeyboardRemove())
        log.warning("slink: raqam mos emas (uid=%s, tg=%s)", uid, tgid)
        return

    # Bu Telegram boshqa akkauntga bog'langan bo'lsa — ikki egalik bo'lmasin
    boshqa = await db_get(
        "SELECT user_id FROM auth_identities "
        "WHERE provider='telegram' AND provider_uid=?", (str(tgid),))
    if boshqa and int(boshqa["user_id"]) != uid:
        await db_run("DELETE FROM seller_tg_link WHERE code=?", (row["code"],))
        await msg.answer(
            "❌ Bu Telegram akkaunti boshqa XazDent hisobiga ulangan.\n\n"
            "Yordam uchun administratorga murojaat qiling.",
            reply_markup=ReplyKeyboardRemove())
        return

    try:
        if not boshqa:
            await db_run(
                "INSERT INTO auth_identities(user_id,provider,provider_uid,"
                "email,display_name) VALUES(?,?,?,?,?)",
                (uid, "telegram", str(tgid), None, msg.from_user.username))
        # ✅ Raqam Telegram tomonidan tasdiqlangan va paneldagi raqam bilan
        # mos tushdi — demak telefon TASDIQLANGAN. Botdan kelgan eski
        # sotuvchilarda `phone_verified` qo'yilmagan edi; shu qadam uni
        # yopadi va ular boshqa SMS so'ralmaydi.
        await db_run(
            "UPDATE users SET phone_verified=1 WHERE id=?", (uid,))
        await db_run("DELETE FROM seller_tg_link WHERE code=?", (row["code"],))
    except Exception as e:
        log.error("slink bog'lash xato (uid=%s): %s", uid, e)
        await msg.answer("❌ Ulashda xatolik. Birozdan so'ng qayta urinib ko'ring.",
                         reply_markup=ReplyKeyboardRemove())
        return

    await msg.answer(
        "✅ *Ulandi!*\n\n"
        "Endi yangi buyurtma kelganda shu yerga xabar keladi va "
        "«✅ Buyurtmani qabul qildim» tugmasi chiqadi.\n\n"
        "_Panelga qaytsangiz «Ulangan» deb ko'rinadi._",
        reply_markup=ReplyKeyboardRemove())
    log.info("slink: uid=%s <-> tg=%s bog'landi", uid, tgid)

    try:
        await _kutayotganlar(uid, tgid)
    except Exception as e:
        log.warning("slink: kutayotgan buyurtmalar xato: %s", e)


async def _kutayotganlar(uid, tgid):
    """Ulangan zahoti — hali qabul qilinmagan TO'LANGAN buyurtmalar.

    Aks holda ulanishdan OLDIN kelgan buyurtmalar sotuvchiga umuman
    ko'rinmay qolardi (xabar o'sha paytda yetib bormagan)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = await db_all(
        "SELECT id, buyer_id, total_amount FROM catalog_orders "
        "WHERE seller_id=? AND status='pending' AND paid_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 10", (uid,))
    for r in (rows or []):
        oid = int(r["id"])
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Buyurtmani qabul qildim",
                                 callback_data="co_confirm_%d_%d"
                                               % (oid, int(r["buyer_id"] or 0))),
            InlineKeyboardButton(text="❌ Mavjud emas",
                                 callback_data="co_reject_%d_%d"
                                               % (oid, int(r["buyer_id"] or 0))),
        ]])
        try:
            await bot.send_message(
                tgid,
                f"💳 *Buyurtma #{oid} TO'LANGAN — tayyorlang!*\n\n"
                f"💰 Jami: {float(r['total_amount'] or 0):,.0f} so'm\n\n"
                f"_Siz ulanishdan oldin kelgan buyurtma._",
                reply_markup=kb)
        except Exception as e:
            log.warning("kutayotgan #%s yuborilmadi: %s", oid, e)
