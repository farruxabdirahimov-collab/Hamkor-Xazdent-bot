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
from app.config import (BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, WEBAPP_URL, BASE_DIR, AD_PRICE_TOSHKENT, AD_PRICE_REGION, AD_PRICE_BOTH_AUD, AD_REGION_PRICES, AD_REGION_DEFAULT, HAMKOR_URL)
from app.database import (init_db, get_user, db_run, db_get, db_all, db_insert, get_setting, update_setting, add_balance, get_next_room_code, generate_order_number, log_order_event, get_or_create_trust_score, update_trust_score, update_seller_metrics, get_pool)
from app.texts import t, REGIONS, REGIONS_RU
from app.keyboards import (ib, ik, kb_cancel, kb_clinic, kb_confirm, kb_deadline, kb_delivery, kb_lang, kb_regions, kb_role, kb_seller, kb_shop_cats, kb_units, rk)
from app.states import (AdState, AdminState, BulkState, CheckoutState, ComplaintState, MyProductsState, NeedState, OfferState, PhotoOrderState, QuickOrderState, RegState, ReviewState, ShopState, SupportState, TopupState)
from app.services import (_build_seller_excel, _create_web_cart_order, _finish_reg, _generate_article_code, _generate_qr_bytes, _get_usd_rate_from_cbu, _handle_web_cart, _notify_loser, _notify_winner, _payment_kb, _post_order_to_group, _save_offer, _save_review, _send_order_to_group, _send_product_qr, _send_quick_order, _show_batch_table, _show_checkout_confirm, _show_delivery_method, _show_product_start, _show_seller_stats, _start_offer_bot, build_excel, build_table, calc_ad_price, delivery_checker, expire_checker, fmt_price, get_or_create_room, has_profile, lang, notify_sellers, notify_sellers_batch, post_batch_to_channel, post_to_channel, usd_rate_checker)
log = logging.getLogger(__name__)


@router.message(F.text == "🔔 Ehtiyojlar")
async def seller_feed(msg: Message):
    needs = await db_all(
        "SELECT n.*, u.region FROM needs n JOIN users u ON n.owner_id=u.id "
        "WHERE n.status='active' ORDER BY n.created_at DESC LIMIT 20"
    )
    if not needs:
        await msg.answer("📭 Hozircha aktiv ehtiyoj yo'q.")
        return

    await msg.answer(f"🔔 *Aktiv ehtiyojlar:* {len(needs)} ta")
    for n in needs:
        existing = await db_get(
            "SELECT id FROM offers WHERE need_id=? AND seller_id=?", (n["id"], msg.from_user.id)
        )
        if existing:
            kb = ik([ib("✅ Taklif yuborilgan", "noop")])
        elif WEBAPP_URL:
            url = f"{WEBAPP_URL}/offer/{n['batch_id'] or n['id']}"
            kb  = ik([ib("💰 Narx kiriting →", web_app=WebAppInfo(url=url))])
        else:
            kb = ik([ib("📤 Taklif yuborish", f"offer_{n['id']}")])

        dl_map = {2: "2 soat", 24: "24 soat", 72: "3 kun", 168: "1 hafta"}
        await msg.answer(
            f"🦷 *{n['product_name']}*\n"
            f"📦 {n['quantity']} {n['unit']}\n"
            f"⏱ {dl_map.get(n['deadline_hours'], '?')} ichida\n"
            f"📍 {n['region'] or ''}",
            reply_markup=kb,
        )

@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer("Allaqachon taklif yubordingiz")

@router.callback_query(F.data.startswith("offer_"))
async def offer_start(call: CallbackQuery, state: FSMContext):
    nid = int(call.data[6:])
    await _start_offer_bot(call, state, nid)
    await call.answer()

@router.callback_query(F.data.startswith("no_stock_"))
async def no_stock(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ *Mavjud emas* deb belgilandi. Rahmat!")
    await call.answer()

@router.message(OfferState.price)
async def offer_price(msg: Message, state: FSMContext):
    try:
        price = float(msg.text.replace(" ", "").replace(",", ""))
    except Exception:
        await msg.answer("❌ Faqat raqam kiriting! _Masalan: 285000_")
        return
    await state.update_data(price=price)
    await state.set_state(OfferState.note)
    await msg.answer(
        "📝 Izoh? _(ixtiyoriy: brend, sifat, muddat...)_",
        reply_markup=ik([ib("⏭ Izohsiz yuborish", "offer_no_note")]),
    )

@router.callback_query(F.data == "offer_no_note", OfferState.note)
async def offer_no_note(call: CallbackQuery, state: FSMContext):
    await _save_offer(call, state, note=None)
    await call.answer()

@router.message(OfferState.note)
async def offer_note(msg: Message, state: FSMContext):
    await _save_offer(msg, state, note=msg.text)

@router.message(F.text == "📤 Takliflarim")
async def my_offers(msg: Message):
    uid  = msg.from_user.id
    offs = await db_all(
        "SELECT o.*, n.product_name as np, n.quantity as nqty, n.unit as nunit "
        "FROM offers o JOIN needs n ON o.need_id=n.id "
        "WHERE o.seller_id=? ORDER BY o.created_at DESC LIMIT 30",
        (uid,),
    )
    if not offs:
        await msg.answer("📭 Hali taklif yubormagansiz.")
        return

    # Jami savdo summasi
    total_won = sum(
        o["price"] * o["nqty"]
        for o in offs if o["status"] == "accepted"
    )
    won_count = sum(1 for o in offs if o["status"] == "accepted")
    pend_count= sum(1 for o in offs if o["status"] == "pending")

    summary = (
        f"📤 *Takliflarim* ({len(offs)} ta)\n\n"
        f"✅ Qabul: *{won_count} ta*\n"
        f"⏳ Kutmoqda: *{pend_count} ta*\n"
        f"💰 Jami savdo: *{total_won:,.0f} so'm*"
    )
    await msg.answer(summary, reply_markup=ik(
        [ib("📊 Batafsil statistika", "seller_stats")],
        [ib("📥 Excel yuklab olish", "seller_excel")],
    ))
    # So'nggi 10 ta
    for o in offs[:10]:
        st = {"pending":"⏳","accepted":"✅","rejected":"❌"}.get(o["status"],"📤")
        total_line = o["price"] * o["nqty"]
        await msg.answer(
            f"{st} *{o['np']}* — {o['nqty']} {o['nunit']}\n"
            f"💰 {o['price']:,.0f} × {o['nqty']} = *{total_line:,.0f} so'm*"
        )

@router.message(F.text == "📊 Statistika")
async def seller_stats_btn(msg: Message):
    await _show_seller_stats(msg.from_user.id, msg)

@router.callback_query(F.data == "seller_stats")
async def seller_stats_cb(call: CallbackQuery):
    await _show_seller_stats(call.from_user.id, call.message)
    await call.answer()

@router.callback_query(F.data == "seller_stats_back")
async def seller_stats_back(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@router.callback_query(F.data == "seller_excel")
async def seller_excel_cb(call: CallbackQuery):
    await call.answer("⏳ Excel tayyorlanmoqda...")
    uid  = call.from_user.id
    path = await _build_seller_excel(uid)
    if not path:
        await call.message.answer("❌ Excel yaratib bo\'lmadi")
        return
    import aiofiles
    async with aiofiles.open(path, "rb") as f:
        data = await f.read()
    fname = f"savdo_{datetime.now().strftime('%Y%m%d')}.xlsx"
    await call.message.answer_document(
        document=BufferedInputFile(data, filename=fname),
        caption=f"📊 Savdo hisoboti — {datetime.now().strftime('%d.%m.%Y')}"
    )
    try:
        import os as _os; _os.remove(path)
    except Exception: pass

@router.message(F.text == "📦 Mahsulotlarim")
async def my_products(msg: Message, state: FSMContext):
    uid  = msg.from_user.id
    rows = await db_all(
        "SELECT * FROM clinic_products WHERE owner_id=? ORDER BY sort_order, id",
        (uid,)
    )
    if not rows:
        await msg.answer(
            "📦 *Mahsulotlar ro\'yxati*\n\nRo\'yxat bo\'sh.\n"
            "Tez-tez buyurtma beradigan mahsulotlarni qo\'shing — "
            "keyingi buyurtmada avtomatik chiqadi.",
            reply_markup=ik([ib("➕ Mahsulot qo\'shish", "prod_add")])
        )
        return
    txt = f"📦 *Mahsulotlarim* ({len(rows)} ta)\n\n"
    for i, r in enumerate(rows, 1):
        txt += f"{i}. *{r['name']}* — {r['unit']}\n"
    await msg.answer(txt, reply_markup=ik(
        [ib("➕ Qo\'shish", "prod_add"), ib("❌ O\'chirish", "prod_del")],
    ))

@router.callback_query(F.data == "prod_add")
async def prod_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(MyProductsState.editing)
    await state.update_data(prod_action="add")
    await call.message.answer(
        "✏️ Mahsulot nomini kiriting:\n\n"
        "_Masalan: GC Fuji IX, Xarizma A2, Spirt_\n\n"
        "/cancel — bekor qilish"
    )
    await call.answer()

@router.callback_query(F.data == "prod_del")
async def prod_del(call: CallbackQuery, state: FSMContext):
    uid  = call.from_user.id
    rows = await db_all(
        "SELECT * FROM clinic_products WHERE owner_id=? ORDER BY sort_order, id", (uid,)
    )
    if not rows:
        await call.answer("Ro\'yxat bo\'sh", show_alert=True)
        return
    kb_rows = []
    for r in rows:
        kb_rows.append([ib(f"❌ {r['name']}", f"prod_del_{r['id']}")])
    kb_rows.append([ib("◀️ Orqaga", "prod_back")])
    await call.message.answer(
        "O\'chirmoqchi bo\'lgan mahsulotni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )
    await call.answer()

@router.callback_query(F.data.startswith("prod_del_"))
async def prod_del_item(call: CallbackQuery):
    pid = int(call.data[9:])
    row = await db_get("SELECT * FROM clinic_products WHERE id=? AND owner_id=?",
                       (pid, call.from_user.id))
    if not row:
        await call.answer("Topilmadi", show_alert=True)
        return
    await db_run("DELETE FROM clinic_products WHERE id=?", (pid,))
    await call.message.edit_text(f"✅ *{row['name']}* o\'chirildi.")
    await call.answer()

@router.callback_query(F.data == "prod_back")
async def prod_back(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@router.message(MyProductsState.editing)
async def prod_add_name(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        await state.clear()
        return
    name = msg.text.strip() if msg.text else ""
    if not name or len(name) < 2:
        await msg.answer("❌ Kamida 2 ta harf kiriting.")
        return
    await state.update_data(prod_name=name)
    await msg.answer(
        f"*{name}* — birligini tanlang:",
        reply_markup=ik(
            [ib("dona","pu_dona"), ib("kg","pu_kg"), ib("litr","pu_litr")],
            [ib("quti","pu_quti"), ib("paket","pu_paket"), ib("ml","pu_ml")],
        )
    )

@router.callback_query(F.data.startswith("pu_"), MyProductsState.editing)
async def prod_add_unit(call: CallbackQuery, state: FSMContext):
    unit = call.data[3:]
    d    = await state.get_data()
    name = d.get("prod_name","")
    uid  = call.from_user.id
    # Mavjudmi?
    ex = await db_get(
        "SELECT id FROM clinic_products WHERE owner_id=? AND name=?", (uid, name)
    )
    if ex:
        await call.message.edit_text(f"⚠️ *{name}* allaqachon ro\'yxatda bor.")
        await state.clear(); await call.answer(); return
    await db_insert(
        "INSERT INTO clinic_products(owner_id,name,unit) VALUES(?,?,?)",
        (uid, name, unit)
    )
    await state.clear()
    await call.message.edit_text(f"✅ *{name}* ({unit}) ro\'yxatga qo\'shildi!")
    await call.answer()

@router.message(F.text == "🏪 Do'konim")
async def my_shop(msg: Message):
    uid  = msg.from_user.id
    shop = await db_get("SELECT * FROM shops WHERE owner_id=? AND status='active'", (uid,))
    if not shop:
        await msg.answer(
            "🏪 Do'koningiz yo'q yoki tasdiqlanmagan.",
            reply_markup=ik([ib("➕ Do'kon ochish", "open_shop")]),
        )
        return
    prod_count = (await db_get("SELECT COUNT(*) as c FROM products WHERE shop_id=? AND is_active=1", (shop["id"],)))["c"]
    catalog_url = f"{HAMKOR_URL}/?uid={uid}" if WEBAPP_URL else None
    add_url = f"{HAMKOR_URL}/?uid={uid}" if WEBAPP_URL else None
    kb_rows = []
    if catalog_url:
        kb_rows.append([ib("🛍 Katalog", web_app=WebAppInfo(url=catalog_url))])
    if add_url:
        kb_rows.append([ib("➕ Mahsulot qo\'shish", web_app=WebAppInfo(url=add_url+"&action=add"))])
    kb_rows.append([ib("📦 Mahsulotlarim (" + str(prod_count) + " ta)", "shop_products")])
    # Guruh holati
    group_id = shop.get("group_chat_id")
    if group_id:
        kb_rows.append([ib("👥 Guruh bog\'langan ✅", "group_info")])
    else:
        kb_rows.append([ib("👥 Guruh ulash (buyurtmalar uchun)", "group_howto")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    rating = float(shop["rating"] or 0)
    stars = ""
    if rating >= 4.5: stars = "⭐⭐⭐⭐⭐"
    elif rating >= 3.5: stars = "⭐⭐⭐⭐"
    elif rating >= 2.5: stars = "⭐⭐⭐"
    elif rating >= 1.5: stars = "⭐⭐"
    elif rating > 0:    stars = "⭐"
    else: stars = "_Hali baholashlar yo\'q_"
    # Baholar soni
    review_count = (await db_get("SELECT COUNT(*) as c FROM reviews WHERE seller_id=?", (uid,)))["c"]
    rate_txt = f"{stars} ({rating:.1f}) · {review_count} ta sharh" if rating > 0 else stars
    await msg.answer(
        f"🏪 *{shop['shop_name']}*\n"
        f"{rate_txt}\n\n"
        f"📂 {shop['category']}\n"
        f"📦 Mahsulotlar: *{prod_count} ta*\n"
        f"🤝 Jami xaridlar: *{shop['total_deals'] or 0} ta*",
        reply_markup=kb
    )

@router.callback_query(F.data == "open_shop")
async def open_shop(call: CallbackQuery, state: FSMContext):
    if not await has_profile(call.from_user.id):
        await call.message.answer(
            "⚠️ Avval profilingizni to'ldiring!",
            reply_markup=ik([ib("✏️ To'ldirish", "edit_profile")]),
        )
        await call.answer()
        return
    await state.set_state(ShopState.cat)
    await call.message.answer("📂 Do'kon kategoriyasini tanlang:", reply_markup=kb_shop_cats())
    await call.answer()

@router.callback_query(F.data.startswith("cat_"), ShopState.cat)
async def shop_cat(call: CallbackQuery, state: FSMContext):
    cats = {
        "cat_1": "🦷 Terapevtik",
        "cat_2": "⚙️ Jarrohlik & Implant",
        "cat_3": "🔬 Zubtexnik",
        "cat_4": "🧪 Dezinfeksiya",
        "cat_5": "💡 Asbob-uskunalar",
    }
    await state.update_data(cat=cats.get(call.data, "Stomatologiya"))
    await state.set_state(ShopState.name)
    await call.message.answer(
        "🏪 Do'kon nomini kiriting:\n\n_Masalan: DentalPlus Toshkent_",
        reply_markup=ReplyKeyboardRemove()
    )
    await call.answer()

@router.message(ShopState.name)
async def shop_name(msg: Message, state: FSMContext):
    d   = await state.get_data()
    u   = await get_user(msg.from_user.id)
    uid = msg.from_user.id
    sname = (msg.text or "").strip()
    if not sname:
        await msg.answer("⚠️ Do'kon nomini kiriting.")
        return
    # Mavjud do'konni yangilaymiz yoki yangisini yaratamiz
    existing = await db_get("SELECT id FROM shops WHERE owner_id=?", (uid,))
    if existing:
        await db_run(
            "UPDATE shops SET shop_name=?, category=?, status='active' WHERE owner_id=?",
            (sname, d.get("cat","Stomatologiya"), uid)
        )
    else:
        await db_insert(
            "INSERT INTO shops(owner_id,shop_name,category,phone,region,status) "
            "VALUES(?,?,?,?,?,'active')",
            (uid, sname, d.get("cat","Stomatologiya"),
             u.get("phone","") if u else "",
             u.get("region","") if u else "")
        )
    await state.clear()
    await msg.answer(
        f"✅ *Do'kon yangilandi!*\n\n🏪 {sname}",
        reply_markup=kb_seller(u["lang"] or "uz", uid=uid, webapp_url=WEBAPP_URL) if u else None
    )
    # Adminga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"🔄 *Do'kon yangilandi*\n\n"
                f"🏪 {sname}\n"
                f"👤 {u.get('full_name','') if u else ''}\n"
                f"📞 {u.get('phone','') if u else ''}\n"
                f"📍 {u.get('region','') if u else ''}\n"
                f"🆔 `{uid}`"
            )
        except Exception:
            pass

@router.callback_query(F.data == "group_info")
async def cb_group_info(call: CallbackQuery):
    uid  = call.from_user.id
    shop = await db_get("SELECT * FROM shops WHERE owner_id=?", (uid,))
    gid  = shop["group_chat_id"] if shop else None
    await call.message.answer(
        f"👥 *Guruh bog\'langan*\n\n"
        f"Guruh ID: `{gid}`\n\n"
        f"Guruh bog\'liqligini o\'chirish uchun:\n"
        f"Guruhda /unsetgroup yozing"
    )
    await call.answer()

@router.callback_query(F.data == "group_howto")
async def cb_group_howto(call: CallbackQuery):
    await call.message.answer(
        "👥 *Guruh ulash — Qo\'llanma*\n\n"
        "1️⃣ Telegram da yangi guruh oching\n"
        "2️⃣ @XazdentBot ni guruhga qo\'shing\n"
        "3️⃣ Botni *Admin* qiling\n"
        "4️⃣ Guruhda /setgroup yozing\n\n"
        "✅ Shundan keyin barcha buyurtmalar guruhga chiqadi.\n"
        "Jamoangizdаn birinchi javob bergan xodim buyurtmani oladi."
    )
    await call.answer()

@router.callback_query(F.data.startswith("shopok_"))
async def shop_ok(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    uid = int(call.data[7:])
    await db_run("UPDATE shops SET status='active' WHERE owner_id=?", (uid,))
    try:
        await bot.send_message(uid, "✅ Do'koningiz faollashdi!")
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n✅ TASDIQLANDI", reply_markup=None)
    await call.answer("✅")

@router.callback_query(F.data.startswith("shoprej_"))
async def shop_rej(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    uid = int(call.data[8:])
    await db_run("UPDATE shops SET status='rejected' WHERE owner_id=?", (uid,))
    await call.message.edit_text(call.message.text + "\n\n❌ RAD ETILDI", reply_markup=None)
    await call.answer("❌")

