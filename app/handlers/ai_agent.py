# -*- coding: utf-8 -*-
"""🤖 AI Agent — sotuvchi mahsulot kartochkasini suhbat orqali tez yaratadi.

Oqim:
  /add yoki "🤖 AI bilan qo'shish" tugmasi → agent rejimi
  Sotuvchi ixtiyoriy tilda yozadi ("uniglover latex ... 45000 som ...")
     → AI ajratadi → kartochka + tugmalar ko'rsatiladi
  Rasm yuborsa → kartochkaga qo'shiladi
  Tugmalar bilan tahrirlaydi → "✅ Tayyor" → xazdent-backend /api/catalog/add_product
     ga yuboriladi (artikul, obuna gating, kanal-post — hammasi backendда).
"""
import os
import base64
import json
import logging
from io import BytesIO

import aiohttp
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.runtime import router, bot
from app.states import AgentState
from app.database import get_user
from app import agent_ai

log = logging.getLogger(__name__)

UPSTREAM = os.getenv("WEB_UPSTREAM", "https://xazdent-bot-production.up.railway.app").rstrip("/")

AGENT_BTN = "🤖 AI bilan qo'shish"

_EDIT = {
    "name":     ("✍️ Yangi *nom* yozing:", "name"),
    "price":    ("💰 *Narx* (so'm, faqat son):", "price"),
    "stock":    ("📦 *Ombor* soni (faqat son):", "stock"),
    "sizes":    ("📐 *Razmerlar* — vergul bilan (masalan: S, M, L, XL):", "sizes"),
    "article":  ("🔢 *Artikul* (masalan: UG-LAT-001):", "article"),
    "desc":     ("📝 Mahsulot *tavsifi*:", "description"),
    "min":      ("📦 *Minimal zakaz* soni (faqat son):", "min_order"),
}


def _empty_card():
    return {"name": "", "category_id": 1, "price": 0, "unit": "dona", "sizes": [],
            "min_order": 1, "stock": 0, "free_all": False, "description": "",
            "article": "", "images": [], "missing": [],
            "img_cands": [], "img_auto": False, "img_idx": 0}


def _md(s):
    """Markdown buzilmasligi uchun xavfli belgilarni tozalaymiz (kartochka ko'rinishi)."""
    s = str(s or "")
    for ch in "*_`[]":
        s = s.replace(ch, "")
    return s


def _card_text(c):
    cat = agent_ai.CATEGORIES.get(c["category_id"], "—")
    lines = [
        "🧾 *Mahsulot kartochkasi*",
        "━━━━━━━━━━━━━━━━━━",
        f"✅ *{_md(c['name']) or '— (nom yo‘q)'}*",
        f"📂 {cat}",
        f"💰 {c['price']:,} so‘m / {c['unit']}".replace(",", " ") if c["price"] else "💰 — (narx yo‘q)",
    ]
    if c["sizes"]:
        lines.append("📐 Razmer: " + " / ".join(_md(x) for x in c["sizes"]))
    lines.append(f"📦 Ombor: {c['stock'] if c['stock'] else '—'}")
    lines.append(f"🧾 Min. zakaz: {c['min_order']} ta")
    lines.append("🚚 " + ("O‘zbekiston bo‘ylab BEPUL yetkazish" if c["free_all"] else "Standart yetkazish"))
    lines.append(f"🔢 Artikul: {_md(c['article']) or '(avtomatik beriladi)'}")
    lines.append(f"🖼 Rasmlar: {len(c['images'])} ta")
    if c["description"]:
        lines.append("")
        lines.append("_" + _md(c["description"]) + "_")
    # yetishmayotgan
    miss = []
    if not c["name"]:
        miss.append("nom")
    if c["price"] <= 0:
        miss.append("narx")
    if not c["images"]:
        miss.append("rasm")
    lines.append("━━━━━━━━━━━━━━━━━━")
    if miss:
        lines.append("⚠️ Yetishmayapti: " + ", ".join(miss))
    else:
        lines.append("✅ Hammasi tayyor — yuklashingiz mumkin!")
    return "\n".join(lines)


def _card_kb(c):
    free_lbl = "🚚 Bepul: ✅" if c["free_all"] else "🚚 Bepul: ❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tayyor, yuklash", callback_data="ag_save")],
        [InlineKeyboardButton(text="🖼 Rasm qo‘shish", callback_data="ag_photo"),
         InlineKeyboardButton(text="✍️ Nom", callback_data="ag_e_name")],
        [InlineKeyboardButton(text="💰 Narx", callback_data="ag_e_price"),
         InlineKeyboardButton(text="📦 Ombor", callback_data="ag_e_stock")],
        [InlineKeyboardButton(text="📐 Razmerlar", callback_data="ag_e_sizes"),
         InlineKeyboardButton(text="🔢 Artikul", callback_data="ag_e_article")],
        [InlineKeyboardButton(text="📝 Tavsif", callback_data="ag_e_desc"),
         InlineKeyboardButton(text="🧾 Min. zakaz", callback_data="ag_e_min")],
        [InlineKeyboardButton(text=free_lbl, callback_data="ag_free"),
         InlineKeyboardButton(text="❌ Bekor", callback_data="ag_cancel")],
    ] + ([[InlineKeyboardButton(text="🔄 Boshqa rasm", callback_data="ag_nextimg")]]
         if c.get("img_cands") else []))


async def _show_card(msg_or_call, c, state, edit=False):
    txt, kb = _card_text(c), _card_kb(c)
    if isinstance(msg_or_call, CallbackQuery):
        try:
            await msg_or_call.message.edit_text(txt, reply_markup=kb)
        except Exception:
            await msg_or_call.message.answer(txt, reply_markup=kb)
    else:
        await msg_or_call.answer(txt, reply_markup=kb)


async def _start_agent(msg: Message, state: FSMContext):
    u = await get_user(msg.from_user.id)
    if not u or u.get("role") != "seller":
        await msg.answer("Bu bo‘lim faqat sotuvchilar uchun. Sotuvchi bo‘lish uchun /start.")
        return
    await state.clear()
    await state.set_state(AgentState.active)
    await state.update_data(card=_empty_card())
    await msg.answer(
        "🤖 *AI Agent yoqildi!*\n\n"
        "Mahsulotni bitta xabar bilan yozing — men kartochkani tayyorlayman.\n\n"
        "_Masalan:_ «uniglover latex qo‘lqop hamma razmerdan bor, narxi 45000 so‘m, "
        "O‘zbekiston bo‘ylab bepul yetkazish, minimal zakaz 10 ta»\n\n"
        "Rasm ham yuborishingiz mumkin. Bekor qilish: /cancel"
    )


# ── Kirish nuqtalari ─────────────────────────────────────────────────────────
@router.message(Command("add"))
async def cmd_add(msg: Message, state: FSMContext):
    await _start_agent(msg, state)


@router.message(F.text == AGENT_BTN)
async def btn_add(msg: Message, state: FSMContext):
    await _start_agent(msg, state)


@router.message(Command("cancel"), AgentState.active)
@router.message(Command("cancel"), AgentState.field)
async def cmd_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("❌ Agent yopildi.")


# ── Asosiy: agent rejimida matn (mahsulot tavsifi) ───────────────────────────
@router.message(AgentState.active, F.text)
async def agent_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    wait = await msg.answer("🧠 O‘qiyapman…")
    extracted, err = await agent_ai.extract_product(msg.text)
    try:
        await wait.delete()
    except Exception:
        pass
    if err == "ai_not_configured":
        await msg.answer("⚠️ AI hozircha sozlanmagan. Admin bilan bog‘laning.")
        return
    if not extracted:
        await msg.answer("😕 Tushunolmadim. Mahsulot nomi va narxini yozib ko‘ring.")
        return
    # yangi ma'lumotlarni mavjud kartochka ustiga qo'yamiz (rasmlarni saqlaymiz)
    imgs = card.get("images") or []
    for k in ("name", "category_id", "price", "unit", "sizes", "min_order",
              "stock", "free_all", "description", "article"):
        v = extracted.get(k)
        if v not in (None, "", 0, [], False):
            card[k] = v
    card["images"] = imgs
    # 🖼 Rasm avtomatik qidiruv — sotuvchi rasm yubormagan bo'lsa, nom bo'yicha topamiz
    if not card["images"] and card["name"]:
        w2 = await msg.answer("🖼 Mos rasm qidiryapman…")
        try:
            cands = await agent_ai.search_images(card["name"], n=6)
            card["img_cands"] = cands
            card["img_idx"] = 0
            for u in cands:
                b64 = await agent_ai.download_image_b64(u)
                if b64:
                    card["images"] = [b64]
                    card["img_auto"] = True
                    break
        except Exception as e:
            log.error(f"auto image xato: {e}")
        try:
            await w2.delete()
        except Exception:
            pass
    await state.update_data(card=card)
    await _show_card(msg, card, state)
    if card.get("img_auto"):
        await msg.answer("🖼 Rasm avtomatik topildi. Noto‘g‘ri bo‘lsa: «🔄 Boshqa rasm» yoki o‘zingiznikini yuboring.")


# ── Rasm qabul qilish (agent rejimida) ───────────────────────────────────────
@router.message(AgentState.active, F.photo)
async def agent_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    try:
        buf = BytesIO()
        await bot.download(msg.photo[-1].file_id, destination=buf)
        raw = buf.getvalue()
        if len(raw) > 3_000_000:
            await msg.answer("⚠️ Rasm juda katta (max 3MB). Kichikroq yuboring.")
            return
        b64 = base64.b64encode(raw).decode()
        # Sotuvchi o'z rasmini yubordi — avtomatik topilgan rasmni almashtiramiz
        if card.get("img_auto"):
            card["images"] = []
            card["img_auto"] = False
            card["img_cands"] = []
        card["images"] = (card.get("images") or [])
        if len(card["images"]) >= 5:
            await msg.answer("⚠️ Maksimum 5 ta rasm.")
            return
        card["images"].append(b64)
        await state.update_data(card=card)
        await msg.answer(f"🖼 Rasm qo‘shildi ({len(card['images'])} ta).")
        await _show_card(msg, card, state)
    except Exception as e:
        log.error(f"agent_photo xato: {e}")
        await msg.answer("⚠️ Rasmni yuklab bo‘lmadi, qayta urinib ko‘ring.")


# ── Maydonni tahrirlash: qiymat kutish ───────────────────────────────────────
@router.message(AgentState.field, F.text)
async def agent_field(msg: Message, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    ef = data.get("ef")
    val = (msg.text or "").strip()
    if ef in ("price", "stock", "min_order"):
        digits = "".join(ch for ch in val if ch.isdigit())
        if not digits:
            await msg.answer("Faqat son kiriting.")
            return
        n = int(digits)
        card[ef] = max(1, n) if ef == "min_order" else n
    elif ef == "sizes":
        card["sizes"] = [s.strip()[:20] for s in val.replace("/", ",").split(",") if s.strip()][:20]
    elif ef == "name":
        card["name"] = val[:200]
    elif ef == "article":
        card["article"] = val[:40]
    elif ef == "description":
        card["description"] = val[:2000]
    await state.update_data(card=card, ef=None)
    await state.set_state(AgentState.active)
    await _show_card(msg, card, state)


# ── Tugmalar (callback) ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("ag_e_"))
async def ag_edit(call: CallbackQuery, state: FSMContext):
    key = call.data[len("ag_e_"):]
    if key not in _EDIT:
        await call.answer(); return
    prompt, _field = _EDIT[key]
    await state.update_data(ef=_EDIT[key][1])
    await state.set_state(AgentState.field)
    if key == "sizes":
        prompt += "\n\n_Yoki razmerlar ko‘rsatilgan rasmni yuboring — men o‘qib olaman._"
    await call.message.answer(prompt)
    await call.answer()


# ── Razmerlarni tahrirlashда rasm yuborilsa — vision bilan o'qiymiz ──────────
@router.message(AgentState.field, F.photo)
async def agent_field_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    if data.get("ef") != "sizes":
        # boshqa maydonni tahrirlashда rasm — uni mahsulot rasmiga qo'shamiz
        await state.update_data(ef=None)
        await state.set_state(AgentState.active)
        return await agent_photo(msg, state)
    wait = await msg.answer("🔎 Rasmdan razmerlarni o‘qiyapman…")
    try:
        buf = BytesIO()
        await bot.download(msg.photo[-1].file_id, destination=buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        sizes, err = await agent_ai.extract_sizes_from_image(f"data:image/jpeg;base64,{b64}")
    except Exception as e:
        log.error(f"vision sizes xato: {e}")
        sizes, err = [], "error"
    try:
        await wait.delete()
    except Exception:
        pass
    if sizes:
        card["sizes"] = sizes
        await msg.answer("📐 Topilgan razmerlar: " + " / ".join(sizes))
    else:
        await msg.answer("😕 Rasmdan razmer topilmadi — qo‘lda vergul bilan yozing (S, M, L).")
    await state.update_data(card=card, ef=None)
    await state.set_state(AgentState.active)
    await _show_card(msg, card, state)


@router.callback_query(F.data == "ag_free")
async def ag_free(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    card["free_all"] = not card.get("free_all")
    await state.update_data(card=card)
    await _show_card(call, card, state, edit=True)
    await call.answer("Bepul yetkazish: " + ("yoqildi" if card["free_all"] else "o‘chirildi"))


@router.callback_query(F.data == "ag_photo")
async def ag_photo_prompt(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🖼 Mahsulot rasm(lar)ini shu yerga yuboring (max 5 ta).")
    await call.answer()


@router.callback_query(F.data == "ag_nextimg")
async def ag_nextimg(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    cands = card.get("img_cands") or []
    if not cands:
        await call.answer("Boshqa rasm yo‘q", show_alert=True); return
    await call.answer("Qidirilyapti…")
    n = len(cands)
    start = int(card.get("img_idx") or 0)
    got = None
    for step in range(1, n + 1):
        idx = (start + step) % n
        b64 = await agent_ai.download_image_b64(cands[idx])
        if b64:
            got = (idx, b64); break
    if not got:
        await call.message.answer("😕 Boshqa mos rasm topilmadi."); return
    card["img_idx"] = got[0]
    card["images"] = [got[1]]
    card["img_auto"] = True
    await state.update_data(card=card)
    await _show_card(call, card, state, edit=True)


@router.callback_query(F.data == "ag_cancel")
async def ag_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer("❌ Agent yopildi.")
    await call.answer()


@router.callback_query(F.data == "ag_save")
async def ag_save(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    card = data.get("card") or _empty_card()
    if not card["name"] or card["price"] <= 0:
        await call.answer("Nom va narx majburiy!", show_alert=True)
        return
    await call.answer("Yuklanmoqda…")
    uid = call.from_user.id
    art = card.get("article") or ""
    variants = [{"size_name": s, "article": (f"{art}-{s}" if art else ""), "stock": card["stock"]}
                for s in (card.get("sizes") or [])]
    payload = {
        "user_id": uid,
        "name": card["name"],
        "price": card["price"],
        "category_id": card["category_id"],
        "categories": [card["category_id"]],
        "unit": card["unit"],
        "description": card["description"],
        "stock": card["stock"],
        "images": card.get("images") or [],
        "variants": variants,
        "delivery_type": "local",
        "delivery_days": "2-3",
        "free_regions": "all" if card["free_all"] else "",
        "installment": 0,
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{UPSTREAM}/api/catalog/add_product", json=payload,
                              timeout=aiohttp.ClientTimeout(total=90)) as r:
                txt = await r.text()
                try:
                    res = json.loads(txt)
                except Exception:
                    res = {"ok": False, "error": txt[:200]}
    except Exception as e:
        log.error(f"ag_save POST xato: {e}")
        await call.message.answer("⚠️ Serverga ulanib bo‘lmadi. Birozdan keyin urinib ko‘ring.")
        return

    if res.get("ok"):
        await state.clear()
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer(
            f"🎉 *Mahsulot joylandi!*\n\n✅ {_md(card['name'])}\n"
            f"💰 {card['price']:,} so‘m".replace(",", " ") +
            "\n\nKatalogда va kanalда ko‘rinadi. Yana qo‘shish: /add")
    elif res.get("error") == "subscription_required":
        await call.message.answer(
            "🔒 *Obuna kerak.*\nMahsulot joylash uchun obuna faollashishi lozim.\n"
            "«⚙️ Profil» yoki «🛍 Dental Market → Obuna» orqali obuna oling.")
    else:
        await call.message.answer("⚠️ Xato: " + str(res.get("error") or "noma'lum"))
