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
from app.database import (init_db, get_user, db_run, db_get, db_all, db_insert, get_setting, update_setting, add_balance, get_next_room_code, generate_order_number, log_order_event, notify_order_event, get_or_create_trust_score, update_trust_score, update_seller_metrics, get_pool)
from app.texts import t, REGIONS, REGIONS_RU
from app.keyboards import (ib, ik, kb_cancel, kb_clinic, kb_confirm, kb_deadline, kb_delivery, kb_lang, kb_regions, kb_role, kb_seller, kb_shop_cats, kb_units, rk)
from app.states import (AdState, AdminState, BulkState, CheckoutState, ComplaintState, MyProductsState, NeedState, OfferState, PhotoOrderState, QuickOrderState, RegState, ReviewState, ShopState, SupportState, TopupState)
from app.services import (_build_seller_excel, _create_web_cart_order, _finish_reg, _generate_article_code, _generate_qr_bytes, _get_usd_rate_from_cbu, _handle_web_cart, _notify_loser, _notify_winner, _payment_kb, _post_order_to_group, _save_offer, _save_review, _send_order_to_group, _send_product_qr, _send_quick_order, _show_batch_table, _show_checkout_confirm, _show_delivery_method, _show_product_start, _show_seller_stats, _start_offer_bot, build_excel, build_table, calc_ad_price, delivery_checker, expire_checker, fmt_price, get_or_create_room, has_profile, lang, notify_sellers, notify_sellers_batch, post_batch_to_channel, post_to_channel, usd_rate_checker)
log = logging.getLogger(__name__)


@router.message(F.text == "/setgroup")
async def cmd_setgroup(msg: Message):
    """Guruhda yozilganda shu guruhni do'konga bog'laydi."""
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer(
            "⚠️ Bu buyruq faqat guruhda ishlaydi.\n\n"
            "Qanday qilish:\n"
            "1. Guruh oching\n"
            "2. Botni guruhga qo'shing (@XazdentBot)\n"
            "3. Botni admin qiling\n"
            "4. Guruhda /setgroup yozing"
        )
        return
    uid      = msg.from_user.id
    group_id = msg.chat.id
    shop     = await db_get(
        "SELECT * FROM shops WHERE owner_id=? AND status='active'", (uid,)
    )
    if not shop:
        await msg.answer("❌ Sizning aktiv do'koningiz topilmadi.")
        return
    await db_run(
        "UPDATE shops SET group_chat_id=? WHERE owner_id=?",
        (group_id, uid)
    )
    await msg.answer(
        f"✅ *{shop['shop_name']}* do'koni shu guruhga bog'landi!\n\n"
        f"Bundan keyin barcha buyurtmalar shu guruhga ham chiqadi.\n"
        f"Guruh ID: `{group_id}`"
    )

@router.message(F.text == "/unsetgroup")
async def cmd_unsetgroup(msg: Message):
    """Guruh bog'liqligini o'chirish."""
    uid  = msg.from_user.id
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    if not shop:
        await msg.answer("❌ Do'kon topilmadi.")
        return
    await db_run("UPDATE shops SET group_chat_id=NULL WHERE owner_id=?", (uid,))
    await msg.answer("✅ Guruh bog'liqligi o'chirildi.")

@router.callback_query(F.data.startswith("claim_"))
async def claim_order(call: CallbackQuery):
    """Guruh a'zosi buyurtmani o'z zimmasiga oladi."""
    parts    = call.data.split("_")
    order_id = int(parts[1])
    claimer  = call.from_user.id
    cname    = call.from_user.full_name or str(claimer)

    order = await db_get("SELECT * FROM catalog_orders WHERE id=?", (order_id,))
    if not order:
        await call.answer("Buyurtma topilmadi", show_alert=True)
        return
    if order["claimed_by"]:
        # Allaqachon birov olgan
        prev = await get_user(order["claimed_by"])
        pname = (prev["clinic_name"] or prev["full_name"] if prev else None) or "Boshqa xodim"
        await call.answer(f"❌ {pname} allaqachon olgan!", show_alert=True)
        return
    if order["status"] != "pending":
        await call.answer("Bu buyurtma allaqachon bajarilgan!", show_alert=True)
        return

    # Claim qilamiz
    await db_run(
        "UPDATE catalog_orders SET claimed_by=? WHERE id=? AND claimed_by IS NULL",
        (claimer, order_id)
    )
    # Tekshiramiz — race condition uchun
    updated = await db_get("SELECT claimed_by FROM catalog_orders WHERE id=?", (order_id,))
    if updated["claimed_by"] != claimer:
        prev = await get_user(updated["claimed_by"])
        pname = (prev["clinic_name"] or prev["full_name"] if prev else None) or "Boshqa xodim"
        await call.answer(f"❌ {pname} birozdan oldin oldi!", show_alert=True)
        return

    # Guruh xabarini yangilaymiz
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (order["seller_id"],))
    shop_name = shop["shop_name"] if shop else "Do'kon"

    import json as _pj
    try:
        items = _pj.loads(order["products_json"] or "[]")
        prod_txt = "\n".join([
            "  • " + str(it.get("name","")) + " " + str(it.get("size","") or "") +
            " — " + str(it.get("qty",0)) + " " + str(it.get("unit","dona"))
            for it in items[:5]
        ])
    except Exception:
        prod_txt = "mahsulotlar"

    try:
        await call.message.edit_text(
            call.message.text + f"\n\n✅ *{cname}* qabul qildi!",
            reply_markup=None
        )
    except Exception: pass

    # Xaridorga kompaniya nomidan xabar
    buyer_id = order["buyer_id"]
    u = await get_user(buyer_id)
    uname = (u["clinic_name"] or u["full_name"] or str(buyer_id)) if u else str(buyer_id)

    try:
        # MAXFIYLIK: do'kon nomi xaridorga KO'RSATILMAYDI
        await buyer_bot.send_message(
            buyer_id,
            f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
            f"Sotuvchi tez orada jo'natadi.\n\n"
            f"📦 {prod_txt}"
        )
    except Exception as e:
        log.error(f"Claim buyer notify xato: {e}")

    # Guruh a'zosiga — MAXFIYLIK: xaridor ismi/telefoni BERILMAYDI, faqat yetkazish hududi/manzili
    try:
        await bot.send_message(
            claimer,
            f"📋 *Buyurtma #{order_id} — Sizning zimmaingizda*\n\n"
            f"📍 {u['region'] if u else '—'}\n"
            f"🏠 {u['address'] if u else '—'}\n\n"
            f"📦 {prod_txt}\n\n"
            f"💰 Jami: *{order['total_amount']:,.0f} so\'m*\n\n"
            f"🔒 _Mijoz ma'lumotlari maxfiy — yetkazishni XazDent muvofiqlashtiradi_"
        )
    except Exception as e:
        log.error(f"Claim claimer notify xato: {e}")

    await call.answer(f"✅ Buyurtma #{order_id} sizda!")


@router.message(F.text == "/setgroup")
async def cmd_setgroup(msg: Message):
    """Guruhda yozilganda shu guruhni do'konga bog'laydi."""
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer(
            "⚠️ Bu buyruq faqat guruhda ishlaydi!\n\n"
            "1. Guruh oching\n"
            "2. Botni guruhga qo\'shing (@XazdentBot)\n"
            "3. Botni admin qiling\n"
            "4. Guruhda /setgroup yozing"
        )
        return

    uid      = msg.from_user.id
    group_id = msg.chat.id
    group_name = msg.chat.title or "Guruh"

    # Bu user ning do'koni bormi?
    shop = await db_get(
        "SELECT * FROM shops WHERE owner_id=? AND status='active'", (uid,))
    if not shop:
        await msg.answer(
            "❌ Sizning faol do\'koningiz topilmadi.\n"
            "Avval @XazdentBot da do\'kon oching."
        )
        return

    await db_run(
        "UPDATE shops SET group_chat_id=? WHERE owner_id=?",
        (group_id, uid)
    )
    await msg.answer(
        f"✅ *{group_name}* guruhi\n"
        f"🏪 *{shop['shop_name']}* do\'koniga bog\'landi!\n\n"
        f"Bundan keyin barcha buyurtmalar shu guruhga ham chiqadi.\n"
        f"_Buyurtmani qabul qilish uchun [✋ Men olaman] tugmasini bosing_"
    )

@router.message(F.text == "/removegroup")
async def cmd_removegroup(msg: Message):
    """Guruhni do'kondan ajratadi."""
    uid = msg.from_user.id
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    if not shop:
        await msg.answer("❌ Do\'kon topilmadi")
        return
    await db_run("UPDATE shops SET group_chat_id=NULL WHERE owner_id=?", (uid,))
    await msg.answer("✅ Guruh bog\'liqlik o\'chirildi")

@router.callback_query(F.data.startswith("claim_order_"))
async def claim_order(call: CallbackQuery):
    """Guruh a'zosi buyurtmani o'z zimmasiga oladi."""
    order_id  = int(call.data[12:])
    claimer   = call.from_user.id
    claimer_name = call.from_user.full_name or "Xodim"

    # Allaqachon qabul qilinganmi?
    order = await db_get(
        "SELECT * FROM catalog_orders WHERE id=?", (order_id,))
    if not order:
        await call.answer("Buyurtma topilmadi", show_alert=True)
        return
    if order["claimed_by"]:
        await call.answer(
            "❌ Bu buyurtmani allaqachon boshqasi qabul qildi!",
            show_alert=True)
        return

    # Claim qilamiz
    await db_run(
        "UPDATE catalog_orders SET claimed_by=?, "
        "claimed_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') "
        "WHERE id=? AND claimed_by IS NULL",
        (claimer, order_id)
    )

    # Tekshiramiz — race condition bo'lmasin
    updated = await db_get(
        "SELECT claimed_by FROM catalog_orders WHERE id=?", (order_id,))
    if not updated or updated["claimed_by"] != claimer:
        await call.answer(
            "❌ Bir soniya kech qoldingiz, boshqasi oldi!",
            show_alert=True)
        return

    # Guruh xabarini yangilaymiz
    import json as _pj
    try:
        items = _pj.loads(order["products_json"] or "[]")
    except Exception:
        items = []

    lines_txt = ""
    for it in items:
        size = it.get("size") or it.get("variant") or ""
        name = it.get("name","?")
        qty  = it.get("qty", 1)
        unit = it.get("unit","dona")
        sub  = it.get("subtotal", 0)
        if size:
            lines_txt += f"• {name} ({size}) — {qty} {unit} · {sub:,.0f} so'm\n"
        else:
            lines_txt += f"• {name} — {qty} {unit} · {sub:,.0f} so'm\n"

    # Guruhga yangilangan xabar
    new_txt = (
        f"📦 *Buyurtma #{order_id}*\n\n"
        f"{lines_txt}\n"
        f"💰 *Jami: {order['total_amount']:,.0f} so'm*\n\n"
        f"✅ *{claimer_name}* qabul qildi!"
    )
    try:
        await call.message.edit_text(new_txt, reply_markup=None)
    except Exception:
        pass

    # Qabul qiluvchiga xaridor kontakti yuboramiz
    buyer  = await get_user(order["buyer_id"])
    shop   = await db_get(
        "SELECT * FROM shops WHERE owner_id=?", (order["seller_id"],))
    sname  = shop["shop_name"] if shop else "Do'kon"

    if buyer:
        uname   = buyer["clinic_name"] or buyer["full_name"] or str(order["buyer_id"])
        uphone  = buyer["phone"] or "—"
        uregion = buyer["region"] or "—"
        uaddr   = buyer["address"] or "—"

        # MAXFIYLIK: xaridor ismi/telefoni BERILMAYDI — faqat yetkazish hududi/manzili
        contact_txt = (
            f"✅ *Buyurtma #{order_id} sizga biriktirildi!*\n\n"
            f"📦 *Buyurtma:*\n{lines_txt}\n"
            f"💰 *Jami: {order['total_amount']:,.0f} so'm*\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Hudud:* {uregion}\n"
            f"🏠 *Manzil:* {uaddr}\n\n"
            f"🔒 _Mijoz ma'lumotlari maxfiy — yetkazishni XazDent muvofiqlashtiradi_"
        )
        try:
            await bot.send_message(claimer, contact_txt)
        except Exception as e:
            log.error(f"Claim contact xato: {e}")

    # Xaridorga ham xabar — MAXFIYLIK: do'kon nomi KO'RSATILMAYDI
    try:
        await bot.send_message(
            order["buyer_id"],
            f"✅ *Buyurtmangiz #{order_id} qabul qilindi!*\n\n"
            f"Sotuvchi xodimi tez orada siz bilan bog\'lanadi."
        )
    except Exception:
        pass

    await call.answer(f"✅ Qabul qildingiz! Xaridor kontakti yuborildi.")

@router.callback_query(F.data.startswith("co_partial_"))
async def catalog_order_partial(call: CallbackQuery, state: FSMContext):
    """Sotuvchi qisman qabul qildi."""
    parts    = call.data.split("_")
    order_id = int(parts[2])
    buyer_id = int(parts[3])
    seller   = call.from_user.id

    order = await db_get("SELECT * FROM catalog_orders WHERE id=?", (order_id,))
    if not order:
        await call.answer("Topilmadi", show_alert=True)
        return

    import json as _pj
    try:
        lines = _pj.loads(order["products_json"] or "[]")
    except Exception:
        lines = []

    await state.set_state(ComplaintState.waiting_reason)
    await state.update_data(
        partial_order_id=order_id,
        partial_buyer_id=buyer_id,
        partial_seller_id=seller
    )

    items_list = "\n".join([
        "  • " + str(it.get("size","?")) + " — " +
        str(int(it.get("qty",1))) + " " + str(it.get("unit","dona"))
        for it in lines
    ])
    await call.message.answer(
        f"⚠️ *Qisman qabul #{order_id}*\n\n"
        f"Buyurtma:\n{items_list}\n\n"
        f"Qaysi razmerlar yoki nechta yo\'qligini yozing:\n"
        f"_Masalan: 5510 razmer yo\'q, 4008 dan faqat 1 ta bor_\n\n"
        f"/cancel — bekor qilish"
    )
    await call.answer()

@router.message(ComplaintState.waiting_reason, F.text)
async def partial_or_complaint_text(msg: Message, state: FSMContext):
    """Qisman qabul yoki shikoyat matni."""
    if msg.text and msg.text.startswith("/"):
        await state.clear()
        await msg.answer("Bekor qilindi.")
        return

    d = await state.get_data()

    # Qisman qabul
    if d.get("partial_order_id"):
        order_id  = d["partial_order_id"]
        buyer_id  = d["partial_buyer_id"]
        seller_id = d["partial_seller_id"]
        reason    = msg.text.strip()
        await state.clear()

        await db_run(
            "UPDATE catalog_orders SET status='partial' WHERE id=?", (order_id,))
        await notify_order_event(order_id, "partial", seller_id)

        u = await get_user(seller_id)
        shop = await db_get("SELECT shop_name FROM shops WHERE owner_id=?", (seller_id,))
        sname = (shop["shop_name"] if shop else None) or                 (u["clinic_name"] if u else None) or "Sotuvchi"

        # Xaridorga
        try:
            await buyer_bot.send_message(
                buyer_id,
                f"⚠️ *Buyurtma #{order_id} — Qisman qabul*\n\n"
                f"🏪 *{sname}* dan xabar:\n"
                f"_{reason}_\n\n"
                f"Sotuvchi siz bilan bog\'lanib aniqlashtiradi."
            )
        except Exception: pass

        await msg.answer(
            f"✅ Xaridorga qisman qabul haqida xabar yuborildi.\n"
            f"Buyurtma #{order_id} aktiv holatda qoldi.")
        return

    # Shikoyat
    order_id  = d.get("order_id")
    seller_id = d.get("seller_id")
    reason    = msg.text.strip()
    buyer_id  = msg.from_user.id
    u         = await get_user(buyer_id)
    uname     = (u["clinic_name"] or u["full_name"] or str(buyer_id)) if u else str(buyer_id)

    await db_insert(
        "INSERT INTO complaints(from_user_id,against_user_id,reason) VALUES(?,?,?)",
        (buyer_id, seller_id, reason))
    await db_run(
        "UPDATE catalog_orders SET status='disputed' WHERE id=?", (order_id,))
    await notify_order_event(order_id, "disputed", buyer_id)
    await state.clear()
    await msg.answer(
        "✅ *Shikoyatingiz qabul qilindi.*\n\n"
        "Admin 24 soat ichida ko\'rib chiqadi.")

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"🚨 *Yangi shikoyat!*\n\n"
                f"👤 {uname} (ID: {buyer_id})\n"
                f"🏪 Sotuvchi ID: {seller_id}\n"
                f"📋 Buyurtma #{order_id}\n\n"
                f"📝 {reason}")
        except Exception: pass

@router.message()
async def fallback(msg: Message, state: FSMContext):
    if msg.chat.type != "private":
        return  # guruhlarda (support/buyurtma guruhi) bot javob bermaydi
    current = await state.get_state()
    if current:
        return  # FSM davom etayotgan bo'lsa ignore
    u  = await get_user(msg.from_user.id)
    lg = (u["lang"] if u else None) or "uz"
    if u and u["role"] in ("clinic", "zubtex"):
        await msg.answer("🏥 *Klinika paneli*", reply_markup=kb_clinic(lg, uid=msg.from_user.id, webapp_url=WEBAPP_URL))
    elif u and u["role"] == "seller":
        uid2 = msg.from_user.id
        await msg.answer("🛒 *Sotuvchi paneli*", reply_markup=kb_seller(lg, uid=uid2, webapp_url=WEBAPP_URL))
    else:
        await msg.answer(t(lg, "welcome"), reply_markup=kb_lang())

