# -*- coding: utf-8 -*-
"""🤝 Potensial sotuvchilar (lead) — hamkor.xazdent.uz dan Telegram orqali kelganlar.

Landingda telefon raqam YO'Q (ega talabi, 2026-10-09): «Telegram'da savol berish»
havolasi shu botni `/start hamkorlik` bilan ochadi.

  • Odam yozgan har bir xabar (matn, rasm, fayl, raqam) «XazDent shartnoma»
    guruhiga (`settings.hamkor_ariza_chat_id`) nusxalanadi; guruh bog'lanmagan
    bo'lsa — ADMIN_IDS ga shaxsiy xabar.
  • Guruhda xodim o'sha xabarga REPLY qilsa — javob bot orqali o'sha odamga boradi
    (bog'lanish `hamkor_lead_xabar` jadvalida: guruh xabari → odamning tg id'si).
  • Odam `hamkor_arizalar` ga manba='telegram' bilan yoziladi — admin panel
    «Potensial sotuvchilar» ro'yxatida sayt arizalari bilan birga ko'rinadi.

Panelga ULANGAN sotuvchilarga tegmaydi: ular odatdagi menyuni ko'radi.
"""
import html
import logging
import time

from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReactionTypeEmoji,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

from app.config import ADMIN_IDS
from app.database import db_all, db_get, db_insert, db_run, get_setting
from app.runtime import bot, router

log = logging.getLogger(__name__)
ARIZA = "hamkor_ariza_chat_id"
LANDING = "https://hamkor.xazdent.uz/hamkorlik#ariza"
DEEP = "hamkorlik"
_JADVAL = {"ok": False}
_TASDIQ = {}            # tg_id → oxirgi «yuborildi» javobi vaqti (har xabarga emas)
TASDIQ_ORALIQ = 600


async def _jadval():
    if _JADVAL["ok"]:
        return
    # Jadvalni asosiy servis (app/hamkorlik.py) ham yaratadi — qaysi biri oldin
    # ishga tushsa, bir xil sxema bo'lsin.
    await db_run("""CREATE TABLE IF NOT EXISTS hamkor_arizalar (
        id SERIAL PRIMARY KEY, korxona TEXT NOT NULL, shakl TEXT DEFAULT '', inn TEXT DEFAULT '',
        telefon TEXT NOT NULL, telefon2 TEXT DEFAULT '', ism TEXT DEFAULT '', hudud TEXT DEFAULT '',
        izoh TEXT DEFAULT '', ip TEXT DEFAULT '', holat TEXT DEFAULT 'yangi',
        yuborildi INTEGER DEFAULT 0, created_at BIGINT DEFAULT 0)""")
    for ust in ("manba TEXT DEFAULT 'sayt'", "tg_id BIGINT DEFAULT 0", "tg_user TEXT DEFAULT ''",
                "admin_izoh TEXT DEFAULT ''", "updated_at BIGINT DEFAULT 0", "xabar_soni INTEGER DEFAULT 0"):
        await db_run("ALTER TABLE hamkor_arizalar ADD COLUMN IF NOT EXISTS " + ust)
    await db_run("""CREATE TABLE IF NOT EXISTS hamkor_lead_xabar (
        chat_id BIGINT NOT NULL, msg_id BIGINT NOT NULL, tg_id BIGINT NOT NULL,
        created_at BIGINT DEFAULT 0, PRIMARY KEY (chat_id, msg_id))""")
    _JADVAL["ok"] = True


def _e(s):
    return html.escape(str(s or ""))


async def _maqsadlar():
    gid = str((await get_setting(ARIZA)) or "").strip()
    try:
        return [int(gid)] if gid else [int(a) for a in ADMIN_IDS]
    except ValueError:
        return [int(a) for a in ADMIN_IDS]


async def _ulangan(tgid):
    from app.seller_link import ulangan_sotuvchi
    return await ulangan_sotuvchi(tgid)


async def _lead(tgid):
    await _jadval()
    return await db_get("SELECT * FROM hamkor_arizalar WHERE manba='telegram' AND tg_id=? "
                        "ORDER BY id DESC LIMIT 1", (int(tgid),))


async def _lead_ol(u):
    """→ (qator, yangimi). Bitta odamga bitta qator."""
    r = await _lead(u.id)
    now = int(time.time())
    if r:
        await db_run("UPDATE hamkor_arizalar SET updated_at=?, tg_user=? WHERE id=?",
                     (now, u.username or "", int(r["id"])))
        return r, False
    aid = await db_insert(
        "INSERT INTO hamkor_arizalar(korxona,telefon,ism,manba,tg_id,tg_user,created_at,updated_at,yuborildi) "
        "VALUES(?,?,?,?,?,?,?,?,1)",
        ("", "", (u.full_name or "")[:120], "telegram", int(u.id), u.username or "", now, now))
    return await db_get("SELECT * FROM hamkor_arizalar WHERE id=?", (int(aid),)), True


def _kim(r, u=None):
    ism = (r["ism"] if r else "") or (u.full_name if u else "") or "—"
    s = "👤 <b>%s</b>" % _e(ism)
    un = (r["tg_user"] if r else "") or (u.username if u else "")
    if un:
        s += " · @%s" % _e(un)
    s += " · <code>#L%d</code>" % int(r["id"])
    if r and r["telefon"]:
        s += "\n📞 %s" % _e(r["telefon"])
    return s


async def _guruhga(r, sarlavha, matn="", nusxa_msg=None):
    """Guruhga (yoki adminlarga) yuboradi va har bir xabarni odamga bog'laydi."""
    tgid = int(r["tg_id"])
    qism = [sarlavha, _kim(r)]
    if matn:
        qism += ["", _e(matn)[:3500]]
    qism += ["", "<i>↩️ Javob berish uchun shu xabarga reply qiling — bot uni yetkazadi.</i>"]
    ok = False
    for cid in await _maqsadlar():
        try:
            m = await bot.send_message(cid, "\n".join(qism), parse_mode="HTML",
                                       disable_web_page_preview=True)
            ids = [m.message_id]
            if nusxa_msg is not None:
                c = await bot.copy_message(cid, nusxa_msg.chat.id, nusxa_msg.message_id,
                                           reply_to_message_id=m.message_id)
                ids.append(c.message_id)
            for mid in ids:
                await db_run("INSERT INTO hamkor_lead_xabar(chat_id,msg_id,tg_id,created_at) VALUES(?,?,?,?) "
                             "ON CONFLICT (chat_id,msg_id) DO NOTHING", (int(cid), int(mid), tgid, int(time.time())))
            ok = True
        except Exception as e:
            log.warning("lead: guruhga yuborilmadi (%s): %s", cid, e)
    return ok


def _kontakt_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamimni yuborish", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


async def _salom(msg_yoki_call_msg, u):
    r, yangi = await _lead_ol(u)
    await msg_yoki_call_msg.answer(
        "🤝 <b>XazDent'da sotuvchi bo'lish</b>\n\n"
        "Assalomu alaykum! Savolingizni shu yerga yozing — menejerimiz <b>shu chatda</b> javob beradi.\n\n"
        "Qo'ng'iroq qilishimizni xohlasangiz — pastdagi tugma bilan raqamingizni yuboring 👇",
        parse_mode="HTML", reply_markup=_kontakt_kb())
    await msg_yoki_call_msg.answer(
        "To'liq ariza (korxona, INN) — saytda, 2 daqiqa:", parse_mode=None,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Ariza qoldirish", url=LANDING)]]))
    if yangi:
        await _guruhga(r, "🆕 <b>Yangi potensial sotuvchi</b> — Telegram (hamkor.xazdent.uz)")
    log.info("lead: tg=%s ochdi (yangi=%s)", u.id, yangi)


# ── /start hamkorlik — landingdagi «Telegram'da savol berish» ───────────────
@router.message(CommandStart(deep_link=True), F.chat.type == "private")
async def lead_start(msg: Message, command: CommandObject, state: FSMContext):
    if (command.args or "").strip().lower() != DEEP:
        raise SkipHandler
    if await _ulangan(msg.from_user.id):
        raise SkipHandler          # ulangan sotuvchi — odatdagi /start
    await state.clear()
    await _salom(msg, msg.from_user)


# ── ulanmagan_javob dagi «🤝 Sotuvchi bo'lmoqchiman» ────────────────────────
@router.callback_query(F.data == "lead_boshla")
async def lead_boshla(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await _salom(call.message, call.from_user)


# ── Guruhda (yoki admin DM'da) lead xabariga REPLY → odamga yetkazish ───────
@router.message(F.reply_to_message)
async def lead_javob(msg: Message):
    rp = msg.reply_to_message
    if not rp or not rp.from_user or rp.from_user.id != bot.id:
        raise SkipHandler
    await _jadval()
    bog = await db_get("SELECT tg_id FROM hamkor_lead_xabar WHERE chat_id=? AND msg_id=?",
                       (int(msg.chat.id), int(rp.message_id)))
    if not bog:
        raise SkipHandler
    if msg.chat.type == "private" and msg.from_user.id not in ADMIN_IDS:
        raise SkipHandler
    tgid = int(bog["tg_id"])
    try:
        if msg.text:
            await bot.send_message(tgid, "💬 <b>XazDent menejeri:</b>\n\n" + _e(msg.text), parse_mode="HTML")
        else:
            await bot.copy_message(tgid, msg.chat.id, msg.message_id)
    except Exception as e:
        log.warning("lead javobi yetmadi (tg=%s): %s", tgid, e)
        await msg.reply("⚠️ Yetkazilmadi: odam botni to'xtatgan bo'lishi mumkin.", parse_mode=None)
        return
    # Javob qaysi lead'ga ketganini guruhda ham bog'laymiz (zanjir davom etsin)
    await db_run("INSERT INTO hamkor_lead_xabar(chat_id,msg_id,tg_id,created_at) VALUES(?,?,?,?) "
                 "ON CONFLICT (chat_id,msg_id) DO NOTHING", (int(msg.chat.id), int(msg.message_id), tgid, int(time.time())))
    await db_run("UPDATE hamkor_arizalar SET holat='boglanildi', updated_at=? "
                 "WHERE manba='telegram' AND tg_id=? AND holat='yangi'", (int(time.time()), tgid))
    try:
        await bot.set_message_reaction(msg.chat.id, msg.message_id, [ReactionTypeEmoji(emoji="👍")])
    except Exception:
        await msg.reply("✅ Yetkazildi", parse_mode=None)
    log.info("lead: javob yetkazildi tg=%s (chat %s)", tgid, msg.chat.id)


# ── seller_link.raqam_bilan_ulash / start.menyu_yoki_ulash chaqiradi ────────
async def lead_raqam(msg, raqam):
    """Ulanmagan odam o'z raqamini yubordi va u hech bir sotuvchiga tegishli emas.
    Lead bo'lsa — raqamini yozib, guruhga yuboradi. → True agar ishlangan bo'lsa."""
    r = await _lead(msg.from_user.id)
    if not r:
        return False
    tel = "+" + str(raqam).lstrip("+")
    await db_run("UPDATE hamkor_arizalar SET telefon=?, updated_at=? WHERE id=?",
                 (tel, int(time.time()), int(r["id"])))
    r = await db_get("SELECT * FROM hamkor_arizalar WHERE id=?", (int(r["id"]),))
    await _guruhga(r, "📞 <b>Potensial sotuvchi raqamini yubordi</b> — qo'ng'iroq qiling")
    await msg.answer("✅ Rahmat! Menejerimiz tez orada <b>%s</b> raqamiga qo'ng'iroq qiladi.\n\n"
                     "Savolingiz bo'lsa — shu yerga yozing." % _e(tel),
                     parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    return True


async def lead_xabar(msg):
    """Ulanmagan odamning oddiy xabari. Lead bo'lsa — guruhga. → True agar ishlangan."""
    if msg.chat.type != "private" or (msg.text or "").startswith("/"):
        return False
    r = await _lead(msg.from_user.id)
    if not r:
        return False
    matn = (msg.text or "").strip()
    nusxa = None if msg.text else msg
    await db_run("UPDATE hamkor_arizalar SET xabar_soni=COALESCE(xabar_soni,0)+1, updated_at=?, "
                 "izoh=LEFT(CASE WHEN COALESCE(izoh,'')='' THEN ? ELSE izoh || E'\\n' || ? END, 2000) WHERE id=?",
                 (int(time.time()), matn or "[media]", matn or "[media]", int(r["id"])))
    ok = await _guruhga(r, "💬 <b>Potensial sotuvchidan savol</b>", matn, nusxa)
    now = time.time()
    if not ok:
        await msg.answer("⚠️ Xabar hozir yetmadi — birozdan keyin qayta yozing.", parse_mode=None)
    elif now - _TASDIQ.get(msg.from_user.id, 0) > TASDIQ_ORALIQ:
        _TASDIQ[msg.from_user.id] = now
        await msg.answer("✅ Menejerga yuborildi. Javob shu chatga keladi.", parse_mode=None)
    return True
