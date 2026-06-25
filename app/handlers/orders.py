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
from app.runtime import bot, dp, router, buyer_bot
from app.config import (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, WEBAPP_URL, BASE_DIR, AD_PRICE_TOSHKENT, AD_PRICE_REGION, AD_PRICE_BOTH_AUD, AD_REGION_PRICES, AD_REGION_DEFAULT)
from app.database import (init_db, get_user, db_run, db_get, db_all, db_insert, get_setting, update_setting, add_balance, get_next_room_code, generate_order_number, log_order_event, get_or_create_trust_score, update_trust_score, update_seller_metrics, get_pool)
from app.texts import t, REGIONS, REGIONS_RU
from app.keyboards import (ib, ik, kb_cancel, kb_clinic, kb_confirm, kb_deadline, kb_delivery, kb_lang, kb_regions, kb_role, kb_seller, kb_shop_cats, kb_units, rk)
from app.states import (AdState, AdminState, BulkState, CheckoutState, ComplaintState, MyProductsState, NeedState, OfferState, PhotoOrderState, QuickOrderState, RegState, ReviewState, ShopState, SupportState, TopupState)
from app.services import (_build_seller_excel, _create_web_cart_order, _finish_reg, _generate_article_code, _generate_qr_bytes, _get_usd_rate_from_cbu, _handle_web_cart, _notify_loser, _notify_winner, _payment_kb, _post_order_to_group, _save_offer, _save_review, _send_order_to_group, _send_product_qr, _send_quick_order, _show_batch_table, _show_checkout_confirm, _show_delivery_method, _show_product_start, _show_seller_stats, _start_offer_bot, build_excel, build_table, calc_ad_price, delivery_checker, expire_checker, fmt_price, get_or_create_room, has_profile, lang, notify_sellers, notify_sellers_batch, post_batch_to_channel, post_to_channel, usd_rate_checker)
log = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("checkout_start_"))
async def checkout_start(call: CallbackQuery, state: FSMContext):
    """Yetkazish bosqichini boshlash. checkout_start_{order_id}_{seller_id}"""
    await call.answer()
    parts = call.data.split("_")
    order_id  = int(parts[2])
    seller_id = int(parts[3])
    uid = call.from_user.id

    u = await get_user(uid)
    saved_addr = u.get("address") or u.get("default_address") or ""
    saved_phone = u.get("phone") or ""

    await state.set_state(CheckoutState.address)
    await state.update_data(
        order_id=order_id, seller_id=seller_id,
        buyer_name=u.get("clinic_name") or u.get("full_name") or str(uid),
        saved_phone=saved_phone
    )

    txt = (
        "🚚 *Yetkazib berish ma'lumotlari*\n\n"
        "📍 *Manzilni kiriting:*\n"
        "_(Ko'cha, uy raqami, mo'ljal)_\n\n"
    )
    if saved_addr:
        txt += f"Saqlangan manzil: `{saved_addr}`"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"✅ Saqlangan manzilni ishlatish",
                callback_data=f"co_use_saved_addr_{order_id}"
            )
        ]])
        await call.message.answer(txt, reply_markup=kb)
    else:
        await call.message.answer(txt)

@router.callback_query(F.data.startswith("co_use_saved_addr_"))
async def checkout_use_saved_addr(call: CallbackQuery, state: FSMContext):
    await call.answer()
    uid = call.from_user.id
    u = await get_user(uid)
    addr = u.get("address") or ""
    await state.update_data(delivery_address=addr)
    await state.set_state(CheckoutState.recipient)
    name = u.get("clinic_name") or u.get("full_name") or ""
    await call.message.answer(
        f"✅ Manzil: `{addr}`\n\n"
        "👤 *Qabul qiluvchi ismini kiriting:*\n"
        "_(Mahsulotni kim qabul qiladi?)_"
    )

@router.message(CheckoutState.address)
async def checkout_address(msg: Message, state: FSMContext):
    addr = msg.text.strip()
    if len(addr) < 5:
        await msg.answer("⚠️ Manzil juda qisqa. Aniqroq yozing.")
        return
    await state.update_data(delivery_address=addr)
    await state.set_state(CheckoutState.recipient)
    await msg.answer(
        f"✅ Manzil: `{addr}`\n\n"
        "👤 *Qabul qiluvchi ismini kiriting:*"
    )

@router.message(CheckoutState.recipient)
async def checkout_recipient(msg: Message, state: FSMContext):
    recipient = msg.text.strip()
    if len(recipient) < 2:
        await msg.answer("⚠️ Ism juda qisqa.")
        return
    data = await state.get_data()
    saved_phone = data.get("saved_phone", "")
    await state.update_data(delivery_recipient=recipient)
    await state.set_state(CheckoutState.phone)

    txt = "📞 *Yetkazish uchun telefon raqam:*\n_(+998 format)_"
    if saved_phone:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"✅ {saved_phone} ni ishlatish",
                callback_data="co_use_saved_phone"
            )
        ]])
        await msg.answer(txt, reply_markup=kb)
    else:
        await msg.answer(txt)

@router.callback_query(F.data == "co_use_saved_phone")
async def checkout_use_saved_phone(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    phone = data.get("saved_phone", "")
    await state.update_data(delivery_phone=phone)
    await _show_delivery_method(call.message, state)

@router.message(CheckoutState.phone)
async def checkout_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+998") and not phone.startswith("998"):
        await msg.answer("⚠️ Telefon formati noto'g'ri.\n+998XXXXXXXXX formatida kiriting.")
        return
    if len(phone.replace("+", "")) < 12:
        await msg.answer("⚠️ Telefon raqam to'liq emas.")
        return
    await state.update_data(delivery_phone=phone)
    await _show_delivery_method(msg, state)

@router.callback_query(F.data.in_({"co_delivery_self", "co_delivery_bts"}))
async def checkout_delivery_method(call: CallbackQuery, state: FSMContext):
    await call.answer()
    method = "seller_self" if call.data == "co_delivery_self" else "bts_express"
    await state.update_data(delivery_method=method)
    data = await state.get_data()
    await _show_checkout_confirm(call.message, state, data, method)

@router.callback_query(F.data == "co_edit_addr", CheckoutState.confirm)
async def checkout_edit_addr(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(CheckoutState.address)
    await call.message.answer("📍 Yangi manzilni kiriting:")

@router.callback_query(F.data == "co_cancel", CheckoutState.confirm)
async def checkout_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.answer("❌ Buyurtma bekor qilindi.")

@router.callback_query(F.data == "co_pay_cod", CheckoutState.confirm)
async def checkout_pay_cod(call: CallbackQuery, state: FSMContext):
    """COD — yetkazilganda to'lov. Buyurtma yaratiladi."""
    await call.answer()
    data      = await state.get_data()
    uid       = call.from_user.id
    order_id  = data.get("order_id")
    seller_id = data.get("seller_id")

    if not order_id or not seller_id:
        await call.message.answer("❌ Xato. Qaytadan urinib ko'ring.")
        await state.clear()
        return

    # catalog_orders ga yetkazish ma'lumotlari saqlash
    await db_run(
        "UPDATE catalog_orders SET "
        "delivery_address=?,delivery_phone=?,"
        "delivery_recipient=?,delivery_method=? "
        "WHERE id=?",
        (
            data.get("delivery_address",""),
            data.get("delivery_phone",""),
            data.get("delivery_recipient",""),
            data.get("delivery_method","seller_self"),
            order_id
        )
    )

    # Orders jadvaliga to'liq yozuv
    ord_num = await generate_order_number()
    co = await db_get("SELECT * FROM catalog_orders WHERE id=?", (order_id,))
    total = float(co.get("total_amount") or 0) if co else 0

    new_oid = await db_insert(
        "INSERT INTO orders(order_number,buyer_id,seller_id,"
        "subtotal,total_amount,payment_method,payment_status,"
        "delivery_method,delivery_address,delivery_phone,"
        "delivery_recipient_name,status,catalog_order_id) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ord_num, uid, seller_id,
            total, total, "cod", "pending",
            data.get("delivery_method","seller_self"),
            data.get("delivery_address",""),
            data.get("delivery_phone",""),
            data.get("delivery_recipient",""),
            "accepted", order_id
        )
    )

    # order_deliveries ga yozish
    await db_insert(
        "INSERT INTO order_deliveries(order_id,method) VALUES(?,?)",
        (new_oid, data.get("delivery_method","seller_self"))
    )

    # Audit log
    await log_order_event(new_oid, "created", "buyer", uid,
                          f"COD, {data.get('delivery_method')}")
    await log_order_event(new_oid, "paid_cod_pending", "system")

    # Trust score yangilash
    await update_trust_score(uid, "created")
    # Sotuvchi metrikalari
    await update_seller_metrics(seller_id, "created")

    await state.clear()

    # Xaridorga tasdiqlash
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📦 Buyurtmalarim",
            callback_data="my_orders"
        )
    ]])
    await call.message.answer(
        f"✅ *Buyurtma qabul qilindi!*\n\n"
        f"📋 Raqam: `{ord_num}`\n"
        f"💰 Jami: *{total:,.0f} so'm*\n"
        f"🚚 Yetkazish: {data.get('delivery_method','seller_self')}\n\n"
        f"Sotuvchi buyurtmangizni ko'rib chiqadi.",
        reply_markup=kb
    )

    # Sotuvchiga yangi xabar
    u = await get_user(uid)
    uname = u.get("clinic_name") or u.get("full_name") or str(uid)
    seller_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Qabul qildim",
                callback_data=f"ord_accept_{new_oid}_{uid}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"ord_reject_{new_oid}_{uid}"
            )
        ]
    ])
    d_txt = "🚗 Sotuvchi o'zi" if data.get("delivery_method") == "seller_self" else "📦 BTS Express"
    try:
        await bot.send_message(
            seller_id,
            f"🆕 *Yangi buyurtma {ord_num}!*\n\n"
            f"👤 Xaridor: *{uname}*\n"
            f"📞 {data.get('delivery_phone','')}\n"
            f"💳 To'lov: 🚚 Yetkazilganda (COD)\n"
            f"🚚 Yetkazish: {d_txt}\n"
            f"📍 {data.get('delivery_address','')}\n\n"
            f"💰 Jami: *{total:,.0f} so'm*\n\n"
            f"⏰ 2 soat ichida javob bering",
            reply_markup=seller_kb
        )
    except Exception as e:
        log.error(f"Sotuvchiga xabar: {e}")

# ── Web savat buyurtmasi: sotuvchi tasdiqlaydi/rad etadi (xaridorga buyer_bot orqali) ──
@router.callback_query(F.data.startswith("co_confirm_"))
async def hk_catalog_confirm(call: CallbackQuery):
    parts = call.data.split("_")
    try:
        order_id = int(parts[2]); buyer_id = int(parts[3])
    except Exception:
        await call.answer(); return
    seller = call.from_user.id
    await db_run(
        "UPDATE catalog_orders SET status='confirmed', "
        "confirmed_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=? AND seller_id=?",
        (order_id, seller))
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(
        f"✅ *Buyurtma #{order_id} qabul qilindi!*\n\n"
        f"Xaridorga xabar yuborildi. Yetkazib bergach, 48 soatdan keyin\n"
        f"baholash so'rovi avtomatik ketadi.")
    shop = await db_get("SELECT shop_name FROM shops WHERE owner_id=?", (seller,))
    u = await get_user(seller)
    sname = (shop["shop_name"] if shop else None) or (u.get("clinic_name") if u else None) or "Sotuvchi"
    try:
        await buyer_bot.send_message(
            buyer_id,
            f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
            f"🏪 *{sname}* buyurtmangizni tasdiqladi va jo'natmoqda.\n\n"
            f"_Yetib kelgach so'raymiz._")
    except Exception as e:
        log.error(f"co_confirm buyer notify xato: {e}")
    await call.answer("✅ Tasdiqlandi!")


@router.callback_query(F.data.startswith("co_reject_"))
async def hk_catalog_reject(call: CallbackQuery):
    parts = call.data.split("_")
    try:
        order_id = int(parts[2]); buyer_id = int(parts[3])
    except Exception:
        await call.answer(); return
    await db_run("UPDATE catalog_orders SET status='rejected' WHERE id=?", (order_id,))
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(f"❌ Buyurtma #{order_id} rad etildi.")
    try:
        await buyer_bot.send_message(
            buyer_id,
            "❌ *Kechirasiz!*\n\nSotuvchida bu mahsulot hozir mavjud emas.\n"
            "Boshqa sotuvchilardan qidirishingiz mumkin 👉 @XazdentBot")
    except Exception:
        pass
    await call.answer("❌ Rad etildi")


@router.callback_query(F.data.startswith("ord_accept_"))
async def order_accept(call: CallbackQuery):
    """Sotuvchi buyurtmani qabul qiladi."""
    await call.answer("✅ Qabul qilindi!")
    parts = call.data.split("_")
    oid     = int(parts[2])
    buyer_id = int(parts[3])
    seller_id = call.from_user.id

    await db_run(
        "UPDATE orders SET status='accepted', "
        "accepted_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (oid,))
    await log_order_event(oid, "accepted", "seller", seller_id)

    # Buyurtma raqamini olish
    ord_row = await db_get("SELECT order_number,total_amount FROM orders WHERE id=?", (oid,))
    ord_num = ord_row["order_number"] if ord_row else f"#{oid}"
    total   = float(ord_row["total_amount"] or 0) if ord_row else 0

    # Sotuvchiga keyingi bosqich
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Tayyorlanmoqda", callback_data=f"ord_preparing_{oid}")],
    ])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ *{ord_num} qabul qilindi!*\n\n"
        "Mahsulotni tayyorlab, xaridorga yetkazing.",
        reply_markup=kb
    )

    # Xaridorga xabar
    try:
        await buyer_bot.send_message(
            buyer_id,
            f"✅ *{ord_num} buyurtmangiz qabul qilindi!*\n\n"
            "Sotuvchi mahsulotni tayyorlayapti.\n"
            "Yetkazish haqida xabar olasiz."
        )
    except Exception as e:
        log.error(f"Xaridorga xabar: {e}")

@router.callback_query(F.data.startswith("ord_reject_"))
async def order_reject_ask(call: CallbackQuery, state: FSMContext):
    """Sotuvchi rad etish — sabab so'raydi."""
    await call.answer()
    parts = call.data.split("_")
    oid      = int(parts[2])
    buyer_id = int(parts[3])
    await state.update_data(rej_order_id=oid, rej_buyer_id=buyer_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Stokda yo'q", callback_data=f"ord_rej_reason_stok_{oid}_{buyer_id}")],
        [InlineKeyboardButton(text="💰 Narx o'zgardi", callback_data=f"ord_rej_reason_narx_{oid}_{buyer_id}")],
        [InlineKeyboardButton(text="🚚 Yetkazib bo'lmaydi", callback_data=f"ord_rej_reason_yetk_{oid}_{buyer_id}")],
        [InlineKeyboardButton(text="✏️ Boshqa sabab", callback_data=f"ord_rej_reason_other_{oid}_{buyer_id}")],
    ])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("❌ Rad etish sababi:", reply_markup=kb)

@router.callback_query(F.data.startswith("ord_rej_reason_"))
async def order_reject_confirm(call: CallbackQuery):
    """Rad etish tasdiqlash."""
    await call.answer()
    parts = call.data.split("_")
    reason_code = parts[3]
    oid      = int(parts[4])
    buyer_id = int(parts[5])
    seller_id = call.from_user.id

    reasons = {
        "stok": "Stokda yo'q",
        "narx": "Narx o'zgardi",
        "yetk": "Yetkazib bo'lmaydi",
        "other": "Boshqa sabab"
    }
    reason = reasons.get(reason_code, "Noma'lum")

    await db_run(
        "UPDATE orders SET status='cancelled',cancellation_reason=?,"
        "cancelled_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (reason, oid))
    await log_order_event(oid, "rejected", "seller", seller_id, reason)
    await update_trust_score(buyer_id, "cancelled")
    await update_seller_metrics(seller_id, "cancelled")

    ord_row = await db_get("SELECT order_number FROM orders WHERE id=?", (oid,))
    ord_num = ord_row["order_number"] if ord_row else f"#{oid}"

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ *{ord_num} rad etildi.*\nSabab: {reason}")

    try:
        await buyer_bot.send_message(
            buyer_id,
            f"❌ *{ord_num} buyurtmangiz rad etildi.*\n\n"
            f"Sabab: {reason}\n\n"
            "Boshqa sotuvchidan buyurtma berishingiz mumkin."
        )
    except Exception as e:
        log.error(f"Xaridorga rad xabari: {e}")

@router.callback_query(F.data.startswith("ord_preparing_"))
async def order_preparing(call: CallbackQuery):
    await call.answer("📦 Tayyorlanmoqda!")
    oid = int(call.data.split("_")[2])
    seller_id = call.from_user.id
    await db_run("UPDATE orders SET status='preparing' WHERE id=?", (oid,))
    await log_order_event(oid, "preparing", "seller", seller_id)

    # Buyurtma raqami va xaridor id
    ord_row = await db_get(
        "SELECT order_number,buyer_id,delivery_method FROM orders WHERE id=?", (oid,))
    ord_num   = ord_row["order_number"] if ord_row else f"#{oid}"
    buyer_id  = ord_row["buyer_id"] if ord_row else None
    method    = (ord_row.get("delivery_method") or "seller_self") if ord_row else "seller_self"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🚚 Yo'lda (yetkazishni boshladim)",
            callback_data=f"ord_shipped_{oid}"
        )
    ]])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"📦 *{ord_num} tayyorlanmoqda*\nMahsulot tayyor bo'lgach yo'lga chiqing.",
        reply_markup=kb
    )
    if buyer_id:
        try:
            await buyer_bot.send_message(
                buyer_id,
                f"📦 *{ord_num}* buyurtmangiz tayyorlanmoqda!\n"
                "Tez orada yetkaziladi."
            )
        except: pass

@router.callback_query(F.data.startswith("ord_shipped_"))
async def order_shipped(call: CallbackQuery, state: FSMContext):
    await call.answer()
    oid = int(call.data.split("_")[2])
    seller_id = call.from_user.id
    ord_row = await db_get(
        "SELECT order_number,buyer_id,delivery_method FROM orders WHERE id=?", (oid,))
    method = (ord_row.get("delivery_method") or "seller_self") if ord_row else "seller_self"

    await db_run(
        "UPDATE orders SET status='shipped',"
        "shipped_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?", (oid,))
    await log_order_event(oid, "shipped", "seller", seller_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Yetkazib berdim",
            callback_data=f"ord_delivered_{oid}"
        )
    ]])

    if method == "bts_express":
        await state.update_data(bts_order_id=oid)
        await call.message.answer(
            "📦 *BTS tracking raqamini kiriting:*\n"
            "_(Masalan: BTS78451236)_\n\n"
            "Yoki tracking raqamsiz davom etish:"
        , reply_markup=kb)
    else:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(
            f"🚚 *Yo'lda!* Xaridorga xabar yuborildi.",
            reply_markup=kb
        )

    buyer_id = ord_row["buyer_id"] if ord_row else None
    ord_num  = ord_row["order_number"] if ord_row else f"#{oid}"
    if buyer_id:
        try:
            track_txt = ""
            if method == "bts_express":
                track_txt = "\nBTS tracking raqami tez orada yuboriladi."
            await buyer_bot.send_message(
                buyer_id,
                f"🚚 *{ord_num}* buyurtmangiz yo'lda!{track_txt}\n"
                "Yetkazib berilganda tasdiqlang."
            )
        except: pass

@router.callback_query(F.data.startswith("ord_delivered_"))
async def order_delivered(call: CallbackQuery):
    await call.answer("✅ Yetkazildi!")
    oid = int(call.data.split("_")[2])
    seller_id = call.from_user.id

    await db_run(
        "UPDATE orders SET status='delivered',"
        "delivered_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?", (oid,))
    await log_order_event(oid, "delivered", "seller", seller_id)

    ord_row  = await db_get(
        "SELECT order_number,buyer_id,total_amount FROM orders WHERE id=?", (oid,))
    ord_num  = ord_row["order_number"] if ord_row else f"#{oid}"
    buyer_id = ord_row["buyer_id"] if ord_row else None
    total    = float(ord_row["total_amount"] or 0) if ord_row else 0

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ *{ord_num} yetkazildi!* Xaridordan tasdiqlash kutilmoqda.")

    if buyer_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, oldim!", callback_data=f"ord_confirm_rcv_{oid}"),
                InlineKeyboardButton(text="❌ Olmadim", callback_data=f"ord_not_rcv_{oid}"),
            ]
        ])
        try:
            await buyer_bot.send_message(
                buyer_id,
                f"📦 *{ord_num}* buyurtmangiz yetkazildi!\n"
                f"💰 Jami: *{total:,.0f} so'm*\n\n"
                "Buyurtmani qabul qildingizmi?",
                reply_markup=kb
            )
        except: pass

@router.callback_query(F.data.startswith("ord_confirm_rcv_"))
async def order_confirm_received(call: CallbackQuery):
    await call.answer("✅ Rahmat!")
    oid = int(call.data.split("_")[3])
    buyer_id = call.from_user.id

    ord_row = await db_get(
        "SELECT order_number,seller_id,total_amount FROM orders WHERE id=?", (oid,))
    ord_num   = ord_row["order_number"] if ord_row else f"#{oid}"
    seller_id = ord_row["seller_id"] if ord_row else None
    total     = float(ord_row["total_amount"] or 0) if ord_row else 0

    await db_run(
        "UPDATE orders SET status='completed',payment_status='paid',"
        "completed_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?", (oid,))
    await log_order_event(oid, "completed", "buyer", buyer_id)

    await update_trust_score(buyer_id, "completed")
    if seller_id:
        await update_seller_metrics(seller_id, "completed", total)

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ *{ord_num} yakunlandi!*\n"
        "Sotuvchiga to'lov o'tkazishni unutmang."
    )
    if seller_id:
        try:
            await bot.send_message(
                seller_id,
                f"✅ *{ord_num} yakunlandi!*\n"
                f"Xaridor qabul qildi. Jami: *{total:,.0f} so'm*"
            )
        except: pass

@router.callback_query(F.data.startswith("ord_not_rcv_"))
async def order_not_received(call: CallbackQuery):
    await call.answer()
    oid = int(call.data.split("_")[3])
    buyer_id = call.from_user.id

    ord_row = await db_get(
        "SELECT order_number,seller_id FROM orders WHERE id=?", (oid,))
    ord_num   = ord_row["order_number"] if ord_row else f"#{oid}"
    seller_id = ord_row["seller_id"] if ord_row else None

    await db_run("UPDATE orders SET status='disputed' WHERE id=?", (oid,))
    await log_order_event(oid, "disputed", "buyer", buyer_id, "Olmadim")
    await update_trust_score(buyer_id, "rejected_delivery")

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"❗ *{ord_num}* uchun muammo qayd etildi.\n"
        "Admin siz bilan bog'lanadi."
    )
    if seller_id:
        try:
            await bot.send_message(
                seller_id,
                f"⚠️ *{ord_num}* — Xaridor olmadim dedi!\n"
                "Admin tekshiradi."
            )
        except: pass


@router.callback_query(F.data.startswith("co_confirm_"))
async def catalog_order_confirm(call: CallbackQuery):
    """Sotuvchi buyurtmani qabul qildi."""
    parts    = call.data.split("_")
    order_id = int(parts[2])
    buyer_id = int(parts[3])
    seller   = call.from_user.id

    await db_run(
        "UPDATE catalog_orders SET status='confirmed', confirmed_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') "
        "WHERE id=? AND seller_id=?",
        (order_id, seller)
    )

    # ── Birinchi buyurtma bonusi — sotuvchi balansiga ────────────────
    # Xaridorning avvalgi tasdiqlangan buyurtmalari sonini tekshiramiz
    prev_orders = await db_get(
        "SELECT COUNT(*) as cnt FROM catalog_orders "
        "WHERE buyer_id=? AND status='confirmed' AND id!=?",
        (buyer_id, order_id)
    )
    is_first = (prev_orders["cnt"] if prev_orders else 0) == 0
    bonus_ball = 50  # 50 ball = settings da 1 ball narxi bo'yicha
    if is_first:
        await db_run(
            "UPDATE users SET balance = COALESCE(balance,0) + ? WHERE id=?",
            (bonus_ball, seller)
        )
        log.info(f"🎁 Birinchi buyurtma bonusi: seller={seller}, buyer={buyer_id}, ball={bonus_ball}")

    # Sotuvchiga tasdiqlash xabari
    await call.message.edit_reply_markup(reply_markup=None)
    bonus_msg = f"\n\n🎁 *+{bonus_ball} ball!* Yangi mijoz uchun bonus!" if is_first else ""
    await call.message.answer(
        f"✅ *Buyurtma #{order_id} qabul qilindi!*\n\n"
        f"Xaridorga xabar yuborildi. 48 soatdan keyin\n"
        f"baholash so\'rovi avtomatik ketadi."
        f"{bonus_msg}"
    )

    # Xaridorga xabar
    u = await get_user(seller)
    shop = await db_get("SELECT shop_name FROM shops WHERE owner_id=?", (seller,))
    sname = (shop["shop_name"] if shop else None) or (u["clinic_name"] if u else None) or "Sotuvchi"
    try:
        first_txt = "\n\n🎉 _Birinchi buyurtmangiz uchun tabriklaymiz!_" if is_first else ""
        await buyer_bot.send_message(
            buyer_id,
            f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
            f"🏪 *{sname}* buyurtmangizni tasdiqladi va\n"
            f"jo\'natmoqda.\n\n"
            f"_48 soatdan keyin yetib kelganini so\'raymiz._"
            f"{first_txt}"
        )
    except Exception as e:
        log.error(f"Buyer notify xato: {e}")
    await call.answer("✅ Tasdiqlandi!")

@router.callback_query(F.data.startswith("co_reject_"))
async def catalog_order_reject(call: CallbackQuery):
    """Sotuvchi buyurtmani rad etdi."""
    parts    = call.data.split("_")
    order_id = int(parts[2])
    buyer_id = int(parts[3])

    await db_run(
        "UPDATE catalog_orders SET status='rejected' WHERE id=?", (order_id,)
    )
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ Buyurtma #{order_id} rad etildi.")

    try:
        await buyer_bot.send_message(
            buyer_id,
            f"❌ *Kechirasiz!*\n\n"
            f"Sotuvchida bu mahsulot hozir mavjud emas.\n"
            f"Boshqa sotuvchilardan qidirishingiz mumkin:\n\n"
            f"👉 @XazdentBot → 🛍 Dental Market"
        )
    except Exception: pass
    await call.answer("❌ Rad etildi")

@router.callback_query(F.data.startswith("co_delivered_"))
async def catalog_order_delivered(call: CallbackQuery):
    """Xaridor yetib kelganini tasdiqladi."""
    parts    = call.data.split("_")
    order_id = int(parts[2])
    seller_id= int(parts[3])
    buyer_id = call.from_user.id

    await db_run(
        "UPDATE catalog_orders SET status='delivered', "
        "delivered_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (order_id,)
    )
    await call.message.edit_reply_markup(reply_markup=None)

    # Baholash so'rovini yuboramiz
    rating_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐", callback_data=f"rate_{order_id}_{seller_id}_1"),
            InlineKeyboardButton(text="⭐⭐", callback_data=f"rate_{order_id}_{seller_id}_2"),
            InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate_{order_id}_{seller_id}_3"),
            InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate_{order_id}_{seller_id}_4"),
            InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate_{order_id}_{seller_id}_5"),
        ]
    ])
    await call.message.answer(
        f"✅ *Ajoyib!*\n\nSotuvchini baholang:",
        reply_markup=rating_kb
    )
    await call.answer()

@router.callback_query(F.data.startswith("co_problem_"))
async def catalog_order_problem(call: CallbackQuery, state: FSMContext):
    """Xaridor muammo bildirdi."""
    parts    = call.data.split("_")
    order_id = int(parts[2])
    seller_id= int(parts[3])

    await state.set_state(ComplaintState.waiting_reason)
    await state.update_data(order_id=order_id, seller_id=seller_id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "😔 *Muammoni tavsiflang:*\n\n"
        "_Masalan: Mahsulot kelmadi, sifat yomon, soni kam..._\n\n"
        "/cancel — bekor qilish"
    )
    await call.answer()

@router.message(ComplaintState.waiting_reason, F.text)
async def complaint_reason(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        await state.clear(); await msg.answer("Bekor qilindi."); return

    d         = await state.get_data()
    order_id  = d.get("order_id")
    seller_id = d.get("seller_id")
    reason    = msg.text.strip()
    buyer_id  = msg.from_user.id
    u         = await get_user(buyer_id)
    uname     = (u["clinic_name"] or u["full_name"] if u else None) or str(buyer_id)

    # DB ga shikoyat
    await db_insert(
        "INSERT INTO complaints(from_user_id,against_user_id,reason) VALUES(?,?,?)",
        (buyer_id, seller_id, reason)
    )
    await db_run(
        "UPDATE catalog_orders SET status='disputed' WHERE id=?", (order_id,)
    )
    await state.clear()
    await msg.answer(
        "✅ *Shikoyatingiz qabul qilindi.*\n\n"
        "Admin 24 soat ichida ko\'rib chiqadi va\n"
        "siz bilan bog\'lanadi."
    )

    # Adminga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"🚨 *Yangi shikoyat!*\n\n"
                f"👤 Xaridor: {uname} (ID: {buyer_id})\n"
                f"🏪 Sotuvchi ID: {seller_id}\n"
                f"📋 Buyurtma #{order_id}\n\n"
                f"📝 {reason}",
                reply_markup=ik(
                    [ib("👥 Users da ko\'rish", "admin_users_check")]
                )
            )
        except Exception: pass

@router.callback_query(F.data.startswith("rate_"))
async def rate_seller(call: CallbackQuery, state: FSMContext):
    """Xaridor yulduz berdi."""
    parts     = call.data.split("_")
    order_id  = int(parts[1])
    seller_id = int(parts[2])
    rating    = int(parts[3])
    buyer_id  = call.from_user.id

    # Avval baholagan bo'lsa qayta baholamasin
    existing = await db_get(
        "SELECT id FROM reviews WHERE order_id=? AND buyer_id=?",
        (order_id, buyer_id)
    )
    if existing:
        await call.answer("Allaqachon baholagansiz!", show_alert=True)
        return

    await state.set_state(ReviewState.waiting_comment)
    await state.update_data(order_id=order_id, seller_id=seller_id, rating=rating)

    stars = "⭐" * rating
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"Baho: {stars}\n\n"
        f"*Izoh qoldiring* (ixtiyoriy):\n"
        f"_Mahsulot sifati, yetkazish tezligi..._",
        reply_markup=ik([ib("➡️ Izohlarsiz yuborish", "review_skip")])
    )
    await call.answer()

@router.callback_query(F.data == "review_skip", ReviewState.waiting_comment)
async def review_skip(call: CallbackQuery, state: FSMContext):
    await _save_review(call.from_user.id, state, comment="")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("✅ Bahoingiz qabul qilindi! Rahmat!")
    await call.answer()

@router.message(ReviewState.waiting_comment, F.text)
async def review_comment(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        await state.clear(); return
    await _save_review(msg.from_user.id, state, comment=msg.text.strip())
    await msg.answer("✅ Bahoingiz va izohingiz qabul qilindi! Rahmat!")

