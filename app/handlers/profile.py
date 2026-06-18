import asyncio
import re
import os
import logging
import json as _json
from datetime import datetime, timedelta
from aiogram import F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, WebAppInfo,
    BufferedInputFile,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.runtime import bot, dp, router
from app.config import (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, WEBAPP_URL, BASE_DIR, AD_PRICE_TOSHKENT, AD_PRICE_REGION, AD_PRICE_BOTH_AUD, AD_REGION_PRICES, AD_REGION_DEFAULT)
from app.database import (init_db, get_user, db_run, db_get, db_all, db_insert, get_setting, update_setting, add_balance, get_next_room_code, generate_order_number, log_order_event, get_or_create_trust_score, update_trust_score, update_seller_metrics, get_pool)
from app.texts import t, REGIONS, REGIONS_RU
from app.keyboards import (ib, ik, kb_cancel, kb_clinic, kb_confirm, kb_deadline, kb_delivery, kb_lang, kb_regions, kb_role, kb_seller, kb_shop_cats, kb_units, rk)
from app.states import (AdState, AdminState, BulkState, CheckoutState, ComplaintState, MyProductsState, NeedState, OfferState, PhotoOrderState, QuickOrderState, RegState, ReviewState, ShopState, SupportState, TopupState)
from app.services import (_build_seller_excel, _create_web_cart_order, _finish_reg, _generate_article_code, _generate_qr_bytes, _get_usd_rate_from_cbu, _handle_web_cart, _notify_loser, _notify_winner, _payment_kb, _post_order_to_group, _save_offer, _save_review, _send_order_to_group, _send_product_qr, _send_quick_order, _show_batch_table, _show_checkout_confirm, _show_delivery_method, _show_product_start, _show_seller_stats, _start_offer_bot, build_excel, build_table, calc_ad_price, delivery_checker, expire_checker, fmt_price, get_or_create_room, has_profile, lang, notify_sellers, notify_sellers_batch, post_batch_to_channel, post_to_channel, usd_rate_checker)
log = logging.getLogger(__name__)


@router.message(F.text == "⚙️ Profil")
async def show_profile(msg: Message, state: FSMContext):
    u  = await get_user(msg.from_user.id)
    lg = u["lang"] or "uz"
    txt = (
        f"⚙️ *Profil*\n\n"
        f"👤 {u['clinic_name'] or '—'}\n"
        f"📞 {u['phone'] or '—'}\n"
        f"📍 {u['region'] or '—'}\n"
        f"🏠 {u['address'] or '—'}\n"
        f"💰 Balans: {u['balance'] or 0:.1f} ball"
    )
    role_label = {"clinic":"🏥 Klinika","zubtex":"🔬 Zubtexnik","seller":"🛒 Sotuvchi"}.get(u["role"],"—")
    txt += f"\n👤 Rol: {role_label}"
    await msg.answer(txt, reply_markup=ik(
        [ib("✏️ Tahrirlash", "edit_profile")],
        [ib("🔄 Rolni o'zgartirish", "change_role")],
        [ib("📢 E'lon berish", "ad_start")],
    ))

@router.callback_query(F.data == "set_payment")
async def set_payment(call: CallbackQuery, state: FSMContext):
    u   = await get_user(call.from_user.id)
    cur = (u.get("payment_methods") or "").split(",") if u else []
    cur = [x for x in cur if x]
    await state.update_data(pm_selected=cur)
    await call.message.answer(
        "💳 *To\'lov usullarini tanlang:*\n_(Bir nechta tanlash mumkin)_",
        reply_markup=_payment_kb(cur)
    )
    await call.answer()

@router.callback_query(F.data.startswith("pm_tog_"))
async def pm_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data[7:]
    d   = await state.get_data()
    sel = list(d.get("pm_selected", []))
    if key in sel: sel.remove(key)
    else: sel.append(key)
    await state.update_data(pm_selected=sel)
    await call.message.edit_reply_markup(reply_markup=_payment_kb(sel))
    await call.answer()

@router.callback_query(F.data == "pm_save")
async def pm_save(call: CallbackQuery, state: FSMContext):
    d   = await state.get_data()
    sel = d.get("pm_selected", [])
    val = ",".join(sel)
    await db_run("UPDATE users SET payment_methods=? WHERE id=?", (val or None, call.from_user.id))
    await state.clear()
    pay_icons = {"p2p":"💳 P2P","cash":"💵 Naqd","bank":"🏦 Hisob raqam"}
    pm_txt = " · ".join(pay_icons[p] for p in sel if p in pay_icons) or "Belgilanmagan"
    await call.message.edit_text(f"✅ Saqlandi: *{pm_txt}*")
    await call.answer("✅")

@router.callback_query(F.data == "pm_cancel")
async def pm_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.delete()
    await call.answer()

@router.callback_query(F.data == "change_role")
async def change_role(call: CallbackQuery):
    lg = await lang(call.from_user.id)
    await call.message.answer(
        "🔄 *Yangi rolingizni tanlang:*",
        reply_markup=ik(
            [ib("🏥 Vrach / Klinika", "role_clinic")],
            [ib("🔬 Zubtexnik",        "role_zubtex")],
            [ib("🛒 Sotuvchi",          "role_seller")],
            [ib("◀️ Orqaga",            "back_profile")],
        )
    )
    await call.answer()

@router.callback_query(F.data == "back_profile")
async def back_profile(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@router.callback_query(F.data == "edit_profile")
async def edit_profile(call: CallbackQuery, state: FSMContext):
    lg = await lang(call.from_user.id)
    u  = await get_user(call.from_user.id)
    await state.set_state(RegState.name)
    if u and u["role"] == "seller":
        ask = "🏪 Do'kon/kompaniya nomingizni kiriting:"
    elif u and u["role"] == "zubtex":
        ask = "🔬 Ismingiz va ish joyingizni kiriting:"
    else:
        ask = "🏥 Klinika nomingizni kiriting:"
    await call.message.answer(ask, reply_markup=ReplyKeyboardRemove())
    await call.answer()

