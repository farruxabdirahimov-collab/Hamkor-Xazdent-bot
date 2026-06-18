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


@router.message(F.text == "💰 Hisobim")
async def show_balance(msg: Message):
    u    = await get_user(msg.from_user.id)
    card = await get_setting("card_number") or "9860020138100068"
    await msg.answer(
        f"💰 *Hisobingiz*\n\n"
        f"⚡️ Ball: *{u['balance'] or 0:.1f}*\n\n"
        f"_(Hozircha e'lon bepul)_",
        reply_markup=ik([ib("➕ Hisob to'ldirish", "topup")]),
    )

@router.callback_query(F.data == "topup")
async def topup_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(TopupState.amount)
    await call.message.answer(
        "💰 *Hisob to'ldirish*\n\n"
        "Qancha so'm o'tkazmoqchisiz?\n_Faqat raqam kiriting._"
    )
    await call.answer()

@router.message(TopupState.amount)
async def topup_amount(msg: Message, state: FSMContext):
    try:
        amount    = float(msg.text.replace(" ", "").replace(",", ""))
        ballprice = float(await get_setting("ball_price") or 1000)
        balls     = amount / ballprice
    except Exception:
        await msg.answer("❌ Faqat raqam kiriting!")
        return
    card = await get_setting("card_number") or "9860020138100068"
    await state.update_data(amount=amount, balls=balls)
    await state.set_state(TopupState.receipt)
    await msg.answer(
        f"✅ *{amount:,.0f} so'm → {balls:.1f} ball*\n\n"
        f"💳 Ushbu kartaga P2P o'tkazing:\n\n"
        f"`{card}`\n_Komilova M_\n\n"
        f"📸 O'tkazma screenshotini yuboring:"
    )

@router.message(TopupState.receipt, F.photo)
async def topup_receipt(msg: Message, state: FSMContext):
    d   = await state.get_data()
    fid = msg.photo[-1].file_id
    tid = await db_insert(
        "INSERT INTO transactions(user_id,amount,balls,type,receipt_file_id) VALUES(?,?,?,'topup',?)",
        (msg.from_user.id, d["amount"], d["balls"], fid),
    )
    u    = await get_user(msg.from_user.id)
    name = u["clinic_name"] or u["full_name"] or str(msg.from_user.id)
    for aid in ADMIN_IDS:
        try:
            await bot.send_photo(
                aid, fid,
                caption=f"💳 *Yangi chek #{tid}*\n\n👤 {name}\n💰 {d['amount']:,.0f} so'm → {d['balls']:.1f} ball",
                reply_markup=ik(
                    [ib("✅ Tasdiqlash", f"adm_ok_{tid}_{msg.from_user.id}_{d['balls']}"),
                     ib("❌ Rad", f"adm_rej_{tid}_{msg.from_user.id}")],
                ),
            )
        except Exception:
            pass
    await state.clear()
    await msg.answer("✅ Chek yuborildi! Admin 15-30 daqiqada tasdiqlaydi.")

@router.callback_query(F.data.startswith("adm_ok_"))
async def adm_ok(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    parts = call.data.split("_")
    tid, uid, balls = int(parts[2]), int(parts[3]), float(parts[4])
    await db_run("UPDATE transactions SET status='confirmed',confirmed_by=? WHERE id=?", (call.from_user.id, tid))
    await add_balance(uid, balls)
    try:
        await bot.send_message(uid, f"🎉 *Hisobingiz to'ldirildi!*\n\n+{balls:.1f} ball")
    except Exception:
        pass
    await call.message.edit_caption(call.message.caption + "\n\n✅ TASDIQLANDI", reply_markup=None)
    await call.answer("✅")

@router.callback_query(F.data.startswith("adm_rej_"))
async def adm_rej(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    parts = call.data.split("_")
    tid, uid = int(parts[2]), int(parts[3])
    await db_run("UPDATE transactions SET status='rejected' WHERE id=?", (tid,))
    try:
        await bot.send_message(uid, "❌ Chekingiz rad etildi. Admin bilan bog'laning.")
    except Exception:
        pass
    await call.message.edit_caption(call.message.caption + "\n\n❌ RAD ETILDI", reply_markup=None)
    await call.answer("❌")

@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    if not WEBAPP_URL:
        await msg.answer("⚠️ WEBAPP_URL sozlanmagan"); return
    uid = msg.from_user.id
    # uid ni URL ga qo'shamiz — Mini App ichida initDataUnsafe ishlamasa ham ishlaydi
    url = f"{WEBAPP_URL}/admin?uid={uid}"
    await msg.answer(
        "👨‍💼 *Admin panel*",
        reply_markup=ik([ib("🖥 Ochish →", web_app=WebAppInfo(url=url))])
    )

@router.message(Command("setball"))
async def cmd_setball(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        val = msg.text.split()[1]
        await update_setting("ball_price", val)
        await msg.answer(f"✅ 1 ball = *{val} so\'m*")
    except Exception: await msg.answer("❌ /setball 2000")

@router.message(Command("setelon"))
async def cmd_setelon(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        val = msg.text.split()[1]
        await update_setting("elon_price", val)
        await msg.answer(f"✅ 1 e\'lon = *{val} ball*")
    except Exception: await msg.answer("❌ /setelon 1")

@router.message(Command("setcard"))
async def cmd_setcard(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        val = msg.text.split()[1]
        await update_setting("card_number", val)
        await msg.answer(f"✅ Karta: `{val}`")
    except Exception: await msg.answer("❌ /setcard 9860...")

@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2: await msg.answer("Format: /broadcast Matn"); return
    users = await db_all("SELECT id FROM users WHERE is_blocked=0")
    sent = 0
    for u in users:
        try: await bot.send_message(u["id"], parts[1]); sent += 1; await asyncio.sleep(0.05)
        except Exception: pass
    await msg.answer(f"✅ Yuborildi: *{sent}* ta")

@router.message(Command("debug"))
async def cmd_debug(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        total_u   = (await db_get("SELECT COUNT(*) as c FROM users"))["c"]
        total_p   = (await db_get("SELECT COUNT(*) as c FROM products"))["c"]
        active_p  = (await db_get("SELECT COUNT(*) as c FROM products WHERE COALESCE(is_active,1)=1"))["c"]
        total_s   = (await db_get("SELECT COUNT(*) as c FROM shops"))["c"]
        active_s  = (await db_get("SELECT COUNT(*) as c FROM shops WHERE status='active'"))["c"]
        # is_active ustuni bormi?
        try:
            test = await db_get("SELECT is_active FROM products LIMIT 1")
            ia_col = f"✅ is_active: {test['is_active'] if test else 'NULL'}"
        except Exception as e:
            ia_col = f"❌ is_active ustun yo'q: {e}"
        # price ustuni variantlarda bormi?
        try:
            test2 = await db_get("SELECT price FROM product_variants LIMIT 1")
            pv_col = f"✅ variant.price: {test2['price'] if test2 else 'NULL'}"
        except Exception as e:
            pv_col = f"❌ variant.price yo'q: {e}"
        # Catalog query test
        # Catalog query test — aynan ishlatadigan query
        test_rows = await db_all(
            "SELECT p.id, p.name, COALESCE(p.is_active,1) as ia, s.status "
            "FROM products p JOIN shops s ON p.shop_id=s.id LIMIT 3"
        )
        # Catalog filtri test
        cat_test = await db_all(
            "SELECT COUNT(*) as c FROM products p "
            "JOIN shops s ON p.shop_id=s.id "
            "WHERE s.status=\'active\' "
            "AND (p.is_active IS NULL OR p.is_active = 1)"
        )
        cat_count = cat_test[0]["c"] if cat_test else "?"
        prod_sample = "\n".join([
            f"  #{r['id']} {r['name'][:20]} ia={r['ia']} shop={r['status']}"
            for r in test_rows
        ]) or "  (bo'sh)"

        text = (
            f"DEBUG INFO\n\n"
            f"Users: {total_u}\n"
            f"Products: {total_p} (aktiv: {active_p})\n"
            f"Shops: {total_s} (aktiv: {active_s})\n"
            f"Catalog query: {cat_count} ta\n\n"
            f"{ia_col}\n"
            f"{pv_col}\n\n"
            f"Sample:\n{prod_sample}"
        )
        await msg.answer(text, parse_mode=None)
    except Exception as e:
        await msg.answer(f"❌ Debug xato: {e}")

@router.message(Command("help"))
async def cmd_help(msg: Message):
    uid = msg.from_user.id
    u   = await get_user(uid)
    if not WEBAPP_URL:
        await msg.answer(
            "📖 *Yordam*\n\n"
            "Klinika: ehtiyoj yozing → takliflar keling → eng arzonni tanlang\n"
            "Sotuvchi: buyurtmalarni ko\'ring → narx kiriting → qabul kuting"
        )
        return
    role = (u["role"] if u else "") or "clinic"
    url  = f"{WEBAPP_URL}/help?role={role}"
    await msg.answer(
        "📖 *Qo\'llanma*\n\nBot qanday ishlashini o\'rganing:",
        reply_markup=ik([ib("📖 Qo\'llanmani ochish →", web_app=WebAppInfo(url=url))])
    )

