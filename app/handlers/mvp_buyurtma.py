# -*- coding: utf-8 -*-
"""🆕 MVP:H — sotuvchi MVP buyurtmalarini shu botdan boshqaradi (panelni ochmasdan).

Shartnoma: asosiy backend `MVP_SHARTNOMA.md` (§3 B, G).

Oqim:
  • Asosiy backend sotuvchiga yangi buyurtma xabarini yuboradi, tugmalar
    callback_data = `mvp:<amal>:<order_id>` (amal: qabul|rad|yolda|yetkazildi).
  • Shu modul tugmani ushlaydi → `POST {BACKEND_URL}/api/mvp/ichki/amal`
    (sarlavha `X-Ichki-Kalit`), tana `{order_id, amal, seller_tg, eta?, sabab?}`.
    Sotuvchi egaligini BACKEND tekshiradi (seller_tg → do'kon egasi).
  • Javobga qarab xabar TAHRIRLANADI: holat qatori + keyingi tugmalar.
  • rad  → sabab tugmalari (Boshqa → matn so'raladi, FSM).
    yolda → ETA tugmalari (Boshqa → matn so'raladi, FSM).
  • /buyurtmalar — ochiq MVP buyurtmalar (bazadan o'qiladi), har biri tugmalar bilan.
  • /tugadi <so'z>, /bor <so'z> — mahsulotni nom bo'yicha topib holatini o'zgartiradi
    (`POST /api/mvp/ichki/mahsulot_holat`).

Ichki tugmalar (backend bilmaydi, faqat shu bot):
  mvpr:<oid>:<i|b>   rad sababi       mvpe:<oid>:<i|b>   yetkazish muddati (ETA)
  mvpo:<oid>         ortga (holatga mos tugmalar)
  mvpm:<t|b|x>:<pid> mahsulot holati (t=tugadi, b=bor, x=bekor)

Xabarlar HTML'da (bot standarti Markdown — har chaqiruvda parse_mode aniq beriladi).
"""
import asyncio
import html
import json
import logging

import aiohttp
from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from app import config as _cfg
from app.runtime import router

log = logging.getLogger(__name__)

HTML = "HTML"


def _e(s):
    """HTML matn uchun escape (apostrof o'zgarmaydi: «Yo'lda»)."""
    return html.escape(str(s), quote=False)

# ── Shartnoma qiymatlari ─────────────────────────────────────────────────
AMALLAR = ("qabul", "rad", "yolda", "yetkazildi")
AMAL_HOLAT = {"qabul": "qabul", "rad": "rad", "yolda": "yolda", "yetkazildi": "yetkazildi"}
OCHIQ_HOLATLAR = ("yangi", "qabul", "yolda", "yetkazildi", "muammo")

HOLAT_MATN = {
    "tolov_kutilmoqda": "⏳ To'lov kutilmoqda",
    "yangi": "🆕 Yangi — qabul qiling",
    "qabul": "✅ Qabul qilindi",
    "yolda": "🚚 Yo'lda",
    "yetkazildi": "📦 Yetkazildi — xaridor tasdig'i kutilmoqda",
    "yopildi": "🏁 Yopildi",
    "rad": "❌ Rad etildi",
    "bekor": "🚫 Bekor qilindi",
    "muammo": "⚠️ Muammo — admin ko'rib chiqmoqda",
}
QISQA = {
    "qabul": "✅ Qabul qilindi",
    "rad": "❌ Rad etildi",
    "yolda": "🚚 Yo'lga chiqdi",
    "yetkazildi": "📦 Yetkazildi deb belgilandi",
}
SABABLAR = ("Tugagan", "Narx o'zgargan", "Yetkaza olmaymiz")
ETALAR = ("Bugun", "Ertaga", "1–2 kun")
TOLOV = {"payme": "Payme", "click": "Click", "rahmat": "Rahmat", "naqd": "💵 Naqd"}

# Kartadagi holat qatori — keyingi tahrirda shu yerdan kesib, yangisi qo'yiladi
MARKER = "\n\n📌 <b>Holat:</b> "


class MvpHolat(StatesGroup):
    rad_sabab = State()   # «Boshqa» sabab matni
    eta = State()         # «Boshqa» yetkazish muddati matni


# ── Sof funksiyalar (DB/tarmoqsiz — testlanadi) ──────────────────────────
def parse_cb(data):
    """`mvp:<amal>:<order_id>` → (amal, order_id) yoki None."""
    try:
        bosh, amal, oid = str(data or "").split(":")
        oid = int(oid)
    except (ValueError, TypeError):
        return None
    if bosh != "mvp" or amal not in AMALLAR or oid <= 0:
        return None
    return amal, oid


def parse_ichki(data, prefiks):
    """`<prefiks>:<oid>:<tanlov>` → (oid, tanlov) yoki None. tanlov: '0'..'9' | 'b'."""
    try:
        bosh, oid, tanlov = str(data or "").split(":")
        oid = int(oid)
    except (ValueError, TypeError):
        return None
    if bosh != prefiks or oid <= 0 or not (tanlov == "b" or tanlov.isdigit()):
        return None
    return oid, tanlov


def tanlov_qiymat(tanlov, royxat):
    """'0'..→ ro'yxatdagi qiymat, 'b' → None (Boshqa: matn so'raladi), xato → ''."""
    if tanlov == "b":
        return None
    try:
        return royxat[int(tanlov)]
    except (ValueError, IndexError):
        return ""


def _btn(matn, data):
    return InlineKeyboardButton(text=matn, callback_data=data)


def tugmalar(oid, holat):
    """Holatga mos keyingi tugmalar (yo'q bo'lsa None — tugmalar olib tashlanadi)."""
    if holat == "yangi":
        rows = [[_btn("✅ Qabul qilish", f"mvp:qabul:{oid}"), _btn("❌ Rad", f"mvp:rad:{oid}")]]
    elif holat == "qabul":
        rows = [[_btn("🚚 Yo'lga chiqdi", f"mvp:yolda:{oid}")], [_btn("❌ Rad", f"mvp:rad:{oid}")]]
    elif holat == "yolda":
        rows = [[_btn("📦 Yetkazildi", f"mvp:yetkazildi:{oid}")]]
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_sabab(oid):
    rows = [[_btn(s, f"mvpr:{oid}:{i}")] for i, s in enumerate(SABABLAR)]
    rows.append([_btn("✍️ Boshqa", f"mvpr:{oid}:b")])
    rows.append([_btn("⬅️ Ortga", f"mvpo:{oid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_eta(oid):
    rows = [[_btn(e, f"mvpe:{oid}:{i}") for i, e in enumerate(ETALAR)]]
    rows.append([_btn("✍️ Boshqa", f"mvpe:{oid}:b")])
    rows.append([_btn("⬅️ Ortga", f"mvpo:{oid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xato_matn(d):
    m = ""
    if isinstance(d, dict):
        m = d.get("error") or d.get("xato") or d.get("message") or ""
    m = str(m or "Amal bajarilmadi.")
    return m[:190]


def yangi_holat(d, amal):
    """Backend javobidagi yangi holat (yo'q bo'lsa — amaldan)."""
    if isinstance(d, dict):
        for k in ("holat", "status", "yangi_holat"):
            v = d.get(k)
            if isinstance(v, str) and v in HOLAT_MATN:
                return v
        b = d.get("buyurtma") or d.get("order")
        if isinstance(b, dict) and b.get("status") in HOLAT_MATN:
            return b["status"]
    return AMAL_HOLAT.get(amal, amal)


def holat_qatori(holat, qoshimcha=None):
    s = MARKER + _e(HOLAT_MATN.get(holat, holat or "—"))
    if qoshimcha:
        s += "\n" + qoshimcha
    return s


def matn_yangila(asl_html, holat, qoshimcha=None, limit=4096):
    """Kartaning eski holat qatorini kesib, yangisini qo'yadi (HTML)."""
    asos = (asl_html or "").split(MARKER)[0].rstrip()
    qator = holat_qatori(holat, qoshimcha)
    if len(asos) + len(qator) > limit:
        asos = asos[: max(0, limit - len(qator) - 1)] + "…"
    return (asos + qator).lstrip()


def qoshimcha_qator(amal, eta=None, sabab=None):
    if amal == "yolda" and eta:
        return "🕒 Yetkazish: " + _e(str(eta))
    if amal == "rad" and sabab:
        return "Sabab: " + _e(str(sabab))
    return None


def _som(x):
    try:
        return f"{float(x or 0):,.0f}".replace(",", " ") + " so'm"
    except (TypeError, ValueError):
        return "—"


def mahsulot_qatorlari(products_json, n=6):
    try:
        items = json.loads(products_json or "[]") if isinstance(products_json, str) else (products_json or [])
    except (TypeError, ValueError):
        return []
    out = []
    for it in (items or [])[:n]:
        if not isinstance(it, dict):
            continue
        nom = it.get("nom") or it.get("name") or it.get("title") or "mahsulot"
        qty = it.get("qty") or it.get("quantity") or it.get("soni") or 1
        out.append(f"• {_e(str(nom))} × {_e(str(qty))}")
    if isinstance(items, list) and len(items) > n:
        out.append(f"… yana {len(items) - n} ta")
    return out


def karta_matn(r):
    """Buyurtma qatori (catalog_orders) → karta matni (HTML)."""
    oid = r.get("id")
    s = [f"🧾 <b>Buyurtma #{oid}</b> — {_som(r.get('total_amount'))}"]
    s += mahsulot_qatorlari(r.get("products_json"))
    if r.get("delivery_address"):
        s.append("📍 " + _e(str(r["delivery_address"])))
    if r.get("delivery_phone"):
        s.append("📞 " + _e(str(r["delivery_phone"])))
    tolov = r.get("tolov_provayder") or r.get("payment_type")
    if tolov:
        s.append("💳 " + _e(TOLOV.get(str(tolov), str(tolov))))
    qosh = None
    if r.get("status") == "yolda" and r.get("eta_text"):
        qosh = "🕒 Yetkazish: " + _e(str(r["eta_text"]))
    return "\n".join(s) + holat_qatori(r.get("status"), qosh)


def mahsulotlar_ol(d):
    """mahsulot_holat qidiruv javobi → [{id, nom, holat}] (kalit nomlariga bardoshli)."""
    items = None
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        for k in ("mahsulotlar", "items", "products", "natija", "data"):
            if isinstance(d.get(k), list):
                items = d[k]
                break
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            pid = int(it.get("id") or it.get("product_id") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        nom = str(it.get("nom") or it.get("name") or f"#{pid}")
        out.append({"id": pid, "nom": nom, "holat": it.get("holat") or ""})
    return out


def kb_mahsulotlar(items, holat):
    h = "t" if holat == "tugadi" else "b"
    belgi = {"bor": "🟢", "tugadi": "🔴", "buyurtmaga": "🟡"}
    rows = [[_btn(f"{belgi.get(it['holat'], '▫️')} {it['nom'][:48]}", f"mvpm:{h}:{it['id']}")]
            for it in items[:10]]
    rows.append([_btn("✖️ Bekor", "mvpm:x:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_mahsulot_cb(data):
    """`mvpm:<t|b|x>:<pid>` → (holat|'x', pid) yoki None."""
    try:
        bosh, h, pid = str(data or "").split(":")
        pid = int(pid)
    except (ValueError, TypeError):
        return None
    if bosh != "mvpm" or h not in ("t", "b", "x"):
        return None
    return ({"t": "tugadi", "b": "bor", "x": "x"}[h], pid)


# ── Backend chaqiruvi ────────────────────────────────────────────────────
async def backend_post(yol, tana):
    """`POST {BACKEND_URL}{yol}` → dict (har doim `ok` kaliti bilan)."""
    if not _cfg.ICHKI_KALIT:
        log.error("ICHKI_KALIT yo'q — MVP amali bajarilmadi (%s)", yol)
        return {"ok": False, "error": "Sozlama xatosi. Administratorga xabar bering."}
    try:
        async with aiohttp.ClientSession() as ss:
            async with ss.post(
                    _cfg.BACKEND_URL + yol, json=tana,
                    # ⚠️ Cloudflare Python'ning standart UA'sini bloklaydi (403, 1010)
                    headers={"X-Ichki-Kalit": _cfg.ICHKI_KALIT, "User-Agent": "curl/8.4.0"},
                    timeout=aiohttp.ClientTimeout(total=25)) as r:
                try:
                    d = await r.json(content_type=None)
                except Exception:
                    d = None
                if not isinstance(d, dict):
                    d = {"ok": r.status < 400, "data": d}
                if r.status >= 400:
                    d["ok"] = False
                    d.setdefault("error", f"Server xatosi ({r.status}). Birozdan so'ng urinib ko'ring.")
                d.setdefault("ok", True)
                return d
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.error("MVP backend xato (%s): %s", yol, e)
    except Exception as e:
        log.exception("MVP backend kutilmagan xato (%s): %s", yol, e)
    return {"ok": False, "error": "Tarmoq xatosi — birozdan so'ng qayta urinib ko'ring."}


async def amal_yubor(oid, amal, seller_tg, eta=None, sabab=None, chat_id=None, message_id=None):
    tana = {"order_id": int(oid), "amal": amal, "seller_tg": int(seller_tg)}
    if eta:
        tana["eta"] = str(eta)[:200]
    if sabab:
        tana["sabab"] = str(sabab)[:300]
    # Qo'shimcha (ixtiyoriy): bosilgan xabar manzili — backend kartani o'zi ham yangilashi uchun
    if chat_id and message_id:
        tana["chat_id"] = int(chat_id)
        tana["message_id"] = int(message_id)
    return await backend_post("/api/mvp/ichki/amal", tana)


# ── Kartani tahrirlash ───────────────────────────────────────────────────
async def kartani_yangila(bot_, chat_id, message_id, caption, matn, kb):
    try:
        if caption:
            await bot_.edit_message_caption(chat_id=chat_id, message_id=message_id,
                                            caption=matn[:1024], parse_mode=HTML, reply_markup=kb)
        else:
            await bot_.edit_message_text(text=matn, chat_id=chat_id, message_id=message_id,
                                         parse_mode=HTML, reply_markup=kb,
                                         disable_web_page_preview=True)
        return True
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return True
        log.warning("MVP karta tahrirlanmadi (%s/%s): %s", chat_id, message_id, e)
    except Exception as e:
        log.warning("MVP karta tahrirlanmadi (%s/%s): %s", chat_id, message_id, e)
    # Matn buzilgan bo'lsa ham — hech bo'lmasa tugmalar to'g'ri bo'lsin
    try:
        await bot_.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=kb)
    except Exception:
        pass
    return False


def _karta_html(m):
    try:
        return m.html_text or ""
    except Exception:
        return _e(m.text or m.caption or "")


async def _tugma_almashtir(call, kb):
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("MVP tugmalar almashmadi: %s", e)


async def _bajar(call: CallbackQuery, oid, amal, eta=None, sabab=None):
    """Callback'dan amal: backend → karta tahriri → qisqa javob."""
    m = call.message
    d = await amal_yubor(oid, amal, call.from_user.id, eta=eta, sabab=sabab,
                         chat_id=m.chat.id if m else None, message_id=m.message_id if m else None)
    if not d.get("ok"):
        await call.answer(xato_matn(d), show_alert=True)
        return False
    holat = yangi_holat(d, amal)
    if m:
        await kartani_yangila(call.bot, m.chat.id, m.message_id, bool(m.caption),
                              matn_yangila(_karta_html(m), holat, qoshimcha_qator(amal, eta, sabab),
                                           limit=1024 if m.caption else 4096),
                              tugmalar(oid, holat))
    await call.answer(QISQA.get(amal, "✅ Bajarildi"))
    return True


async def _holat_ol(oid):
    """Buyurtmaning joriy holati (bazadan). Xato bo'lsa — 'yangi'."""
    try:
        from app.database import db_get
        r = await db_get("SELECT status FROM catalog_orders WHERE id=?", (int(oid),))
        if r and r.get("status"):
            return r["status"]
    except Exception as e:
        log.warning("MVP holat o'qilmadi (#%s): %s", oid, e)
    return "yangi"


# ── Backend tugmalari: mvp:<amal>:<order_id> ─────────────────────────────
@router.callback_query(F.data.startswith("mvp:"))
async def cb_mvp_amal(call: CallbackQuery, state: FSMContext):
    p = parse_cb(call.data)
    if not p:
        await call.answer("Noma'lum amal.", show_alert=True)
        return
    amal, oid = p
    await state.clear()
    if amal == "rad":
        await _tugma_almashtir(call, kb_sabab(oid))
        await call.answer("Rad etish sababini tanlang")
        return
    # «Yo'lga chiqdi» — yetkazish muddati so'ralmaydi (logistika bilan aloqa yo'q, faqat holat)
    await _bajar(call, oid, amal)


async def _boshqa_sora(call: CallbackQuery, state: FSMContext, oid, holat_st, savol):
    m = call.message
    await state.set_state(holat_st)
    await state.update_data(mvp_oid=oid, mvp_chat=m.chat.id, mvp_msg=m.message_id,
                            mvp_caption=bool(m.caption), mvp_html=_karta_html(m))
    await call.answer()
    await m.answer(savol + "\n\nBekor qilish: /bekor", parse_mode=None)


@router.callback_query(F.data.startswith("mvpr:"))
async def cb_mvp_sabab(call: CallbackQuery, state: FSMContext):
    p = parse_ichki(call.data, "mvpr")
    if not p:
        await call.answer("Noma'lum tugma.", show_alert=True)
        return
    oid, tanlov = p
    sabab = tanlov_qiymat(tanlov, SABABLAR)
    if sabab is None:
        await _boshqa_sora(call, state, oid, MvpHolat.rad_sabab,
                           f"✍️ Buyurtma #{oid}: rad etish sababini yozing.")
        return
    if not sabab:
        await call.answer("Noma'lum tugma.", show_alert=True)
        return
    await state.clear()
    await _bajar(call, oid, "rad", sabab=sabab)


@router.callback_query(F.data.startswith("mvpe:"))
async def cb_mvp_eta(call: CallbackQuery, state: FSMContext):
    p = parse_ichki(call.data, "mvpe")
    if not p:
        await call.answer("Noma'lum tugma.", show_alert=True)
        return
    oid, tanlov = p
    eta = tanlov_qiymat(tanlov, ETALAR)
    if eta is None:
        await _boshqa_sora(call, state, oid, MvpHolat.eta,
                           f"✍️ Buyurtma #{oid}: qachon yetkazasiz? (masalan: «Juma kuni»)")
        return
    if not eta:
        await call.answer("Noma'lum tugma.", show_alert=True)
        return
    await state.clear()
    await _bajar(call, oid, "yolda", eta=eta)


@router.callback_query(F.data.startswith("mvpo:"))
async def cb_mvp_ortga(call: CallbackQuery, state: FSMContext):
    try:
        oid = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    await state.clear()
    await _tugma_almashtir(call, tugmalar(oid, await _holat_ol(oid)))
    await call.answer()


# ── FSM: «Boshqa» sabab / muddat matni ───────────────────────────────────
async def _fsm_matn(msg: Message, state: FSMContext, amal):
    t = (msg.text or "").strip()
    if t.startswith("/"):
        await state.clear()
        if t.split()[0].split("@")[0].lower() in ("/bekor", "/cancel"):
            await msg.answer("Bekor qilindi.", parse_mode=None)
            return
        raise SkipHandler            # boshqa buyruq — o'z handleriga o'tsin
    if len(t) < 2:
        await msg.answer("Kamida 2 ta belgi yozing (yoki /bekor).", parse_mode=None)
        return
    d0 = await state.get_data()
    oid = d0.get("mvp_oid")
    await state.clear()
    if not oid:
        await msg.answer("Buyurtma topilmadi — tugmani qayta bosing.", parse_mode=None)
        return
    eta = t[:200] if amal == "yolda" else None
    sabab = t[:300] if amal == "rad" else None
    d = await amal_yubor(oid, amal, msg.from_user.id, eta=eta, sabab=sabab,
                         chat_id=d0.get("mvp_chat"), message_id=d0.get("mvp_msg"))
    if not d.get("ok"):
        await msg.answer("⚠️ " + xato_matn(d) + "\nTugmani qayta bosib ko'ring.", parse_mode=None)
        return
    holat = yangi_holat(d, amal)
    if d0.get("mvp_chat") and d0.get("mvp_msg"):
        cap = bool(d0.get("mvp_caption"))
        await kartani_yangila(msg.bot, d0["mvp_chat"], d0["mvp_msg"], cap,
                              matn_yangila(d0.get("mvp_html") or "", holat,
                                           qoshimcha_qator(amal, eta, sabab),
                                           limit=1024 if cap else 4096),
                              tugmalar(oid, holat))
    await msg.answer(f"{QISQA.get(amal, '✅ Bajarildi')} — buyurtma #{oid}", parse_mode=None)


@router.message(MvpHolat.rad_sabab, F.text)
async def fsm_rad_sabab(msg: Message, state: FSMContext):
    await _fsm_matn(msg, state, "rad")


@router.message(MvpHolat.eta, F.text)
async def fsm_eta(msg: Message, state: FSMContext):
    await _fsm_matn(msg, state, "yolda")


# ── /buyurtmalar — ochiq MVP buyurtmalar ─────────────────────────────────
async def ochiq_buyurtmalar(uid, limit=20):
    from app.database import db_all
    return await db_all(
        "SELECT id, status, total_amount, products_json, delivery_address, delivery_phone, "
        "eta_text, tolov_provayder, payment_type FROM catalog_orders "
        "WHERE model='mvp' AND status IN ('yangi','qabul','yolda','yetkazildi','muammo') "
        "AND (shop_id IN (SELECT id FROM shops WHERE owner_id=?) OR seller_id=?) "
        "ORDER BY id DESC LIMIT " + str(int(limit)),
        (int(uid), int(uid)))


async def buyurtmalar_royxati(msg: Message):
    """Ochiq MVP buyurtmalar — har biri alohida karta, tugmalari bilan.
    (Menyudagi «🔔 Buyurtmalar» ham MVP rejimida shu yerga keladi.)"""
    from app.seller_link import ulangan_sotuvchi
    suid = await ulangan_sotuvchi(msg.from_user.id)
    if not suid:
        await msg.answer("Bu Telegram sotuvchi paneliga ulanmagan. /start", parse_mode=None)
        return
    try:
        rows = await ochiq_buyurtmalar(suid)
    except Exception as e:
        log.error("MVP buyurtmalar o'qilmadi (uid=%s): %s", suid, e)
        await msg.answer("⚠️ Buyurtmalarni o'qib bo'lmadi. Birozdan so'ng urinib ko'ring.",
                         parse_mode=None)
        return
    if not rows:
        await msg.answer("📭 Ochiq buyurtma yo'q.", parse_mode=None)
        return
    await msg.answer(f"🔔 <b>Ochiq buyurtmalar:</b> {len(rows)} ta", parse_mode=HTML)
    for r in rows:
        try:
            await msg.answer(karta_matn(r), parse_mode=HTML,
                             reply_markup=tugmalar(int(r["id"]), r.get("status")),
                             disable_web_page_preview=True)
        except Exception as e:
            log.warning("MVP karta #%s yuborilmadi: %s", r.get("id"), e)


async def kutayotganlar_yubor(uid, tgid, bot_):
    """Sotuvchi botga endi ulandi — kutayotgan MVP buyurtmalar kartalari.
    (seller_link._kutayotganlar MVP rejimida shuni chaqiradi.)"""
    rows = await ochiq_buyurtmalar(uid, limit=10)
    for r in rows or []:
        if r.get("status") not in ("yangi", "qabul", "yolda"):
            continue
        try:
            await bot_.send_message(int(tgid), karta_matn(r), parse_mode=HTML,
                                    reply_markup=tugmalar(int(r["id"]), r.get("status")),
                                    disable_web_page_preview=True)
        except Exception as e:
            log.warning("MVP kutayotgan #%s yuborilmadi: %s", r.get("id"), e)


@router.message(Command("buyurtmalar"))
async def cmd_buyurtmalar(msg: Message, state: FSMContext):
    if msg.chat.type != "private":
        return
    await state.clear()
    await buyurtmalar_royxati(msg)


# ── /tugadi <so'z>, /bor <so'z> ──────────────────────────────────────────
@router.message(Command("tugadi", "bor"))
async def cmd_mahsulot_holat(msg: Message, command: CommandObject, state: FSMContext):
    if msg.chat.type != "private":
        return
    await state.clear()
    holat = "tugadi" if command.command.lower() == "tugadi" else "bor"
    soz = (command.args or "").strip()
    if len(soz) < 2:
        await msg.answer(f"Mahsulot nomidan bir so'z yozing:\n/{holat} kompozit", parse_mode=None)
        return
    d = await backend_post("/api/mvp/ichki/mahsulot_holat",
                           {"seller_tg": int(msg.from_user.id), "qidiruv": soz[:100]})
    if not d.get("ok"):
        await msg.answer("⚠️ " + xato_matn(d), parse_mode=None)
        return
    items = mahsulotlar_ol(d)
    if not items:
        await msg.answer(f"🔍 «{soz}» bo'yicha mahsulot topilmadi.", parse_mode=None)
        return
    nima = "🔴 tugadi" if holat == "tugadi" else "🟢 bor"
    qosh = "\n(birinchi 10 tasi; aniqroq yozing)" if len(items) > 10 else ""
    await msg.answer(f"Qaysi mahsulot «{nima}» bo'lsin?{qosh}", parse_mode=None,
                     reply_markup=kb_mahsulotlar(items, holat))


def _tugma_nomi(call: CallbackQuery):
    try:
        for row in call.message.reply_markup.inline_keyboard:
            for b in row:
                if b.callback_data == call.data:
                    return b.text.split(" ", 1)[-1]
    except Exception:
        pass
    return ""


@router.callback_query(F.data.startswith("mvpm:"))
async def cb_mahsulot_holat(call: CallbackQuery):
    p = parse_mahsulot_cb(call.data)
    if not p:
        await call.answer("Noma'lum tugma.", show_alert=True)
        return
    holat, pid = p
    if holat == "x":
        try:
            await call.message.edit_text("✖️ Bekor qilindi.", parse_mode=None)
        except Exception:
            pass
        await call.answer()
        return
    d = await backend_post("/api/mvp/ichki/mahsulot_holat",
                           {"seller_tg": int(call.from_user.id), "product_id": pid, "holat": holat})
    if not d.get("ok"):
        await call.answer(xato_matn(d), show_alert=True)
        return
    nom = str(d.get("nom") or d.get("name") or _tugma_nomi(call) or f"#{pid}")
    nima = "🔴 tugadi" if holat == "tugadi" else "🟢 bor"
    try:
        await call.message.edit_text(f"✅ «{nom}» — {nima} deb belgilandi.", parse_mode=None)
    except Exception:
        pass
    await call.answer("✅ Saqlandi")


async def eski_bolim(msg: Message):
    """Yashirilgan eski bo'lim (balans, profil, AI agent) — eski klaviaturadan bosilsa.
    Yangi menyu ham shu yerda beriladi (eski tugmalar yo'qolsin)."""
    try:
        from app.seller_link import ulangan_sotuvchi
        from app.handlers.start import sotuvchi_menyu
        suid = await ulangan_sotuvchi(msg.from_user.id)
        if suid:
            await msg.answer("Bu bo'lim endi «🏪 Sotuvchi kabineti»da.", parse_mode=None)
            await sotuvchi_menyu(msg, suid)
            return
    except Exception as e:
        log.warning("eski bo'lim: menyu berilmadi: %s", e)
    await msg.answer("Bu bo'lim endi «🏪 Sotuvchi kabineti»da. /start", parse_mode=None)


# ── MVP yordam matni (start.seller_help MVP rejimida shuni ko'rsatadi) ────
YORDAM = (
    "📖 <b>Yordam</b>\n\n"
    "🔔 Yangi buyurtma shu botga keladi — tugmalar bilan:\n"
    "✅ Qabul → 🚚 Yo'lga chiqdi → 📦 Yetkazildi (yoki ❌ Rad)\n\n"
    "/buyurtmalar — ochiq buyurtmalar\n"
    "/tugadi <i>nom</i> — mahsulot tugadi\n"
    "/bor <i>nom</i> — mahsulot yana bor\n\n"
    "🏪 Qolgan hammasi — «Sotuvchi kabineti»da."
)
