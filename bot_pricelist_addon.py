"""
Bu faylni bot.py ga qo'shish uchun:
1. bot.py boshiga qo'shing: from bot_pricelist_addon import register_pricelist_handlers
2. main() ichida dp.start_polling(bot) dan OLDIN qo'shing: register_pricelist_handlers(dp)
"""

import asyncio
import logging
from aiogram import F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from price_list_handler import process_price_list

logger = logging.getLogger(__name__)


def register_pricelist_handlers(dp, bot, product_cache, upload_to_xazdent, is_admin, seller_sessions):

    @dp.message(F.document)
    async def handle_document(message: Message):
        uid = message.from_user.id
        if not is_admin(uid) and uid not in seller_sessions:
            await message.answer("⛔ Avval /start bosing.")
            return

        doc = message.document
        filename = doc.file_name or "file"
        mime_type = doc.mime_type or ""
        file_size = doc.file_size or 0

        if file_size > 20 * 1024 * 1024:
            await message.answer("⚠️ Fayl 20MB dan katta.")
            return

        allowed = ['.pdf', '.xlsx', '.xls', '.docx', '.doc', '.jpg', '.jpeg', '.png']
        if not any(filename.lower().endswith(e) for e in allowed):
            await message.answer("⚠️ Faqat PDF, Excel, Word, JPG, PNG qabul qilinadi.")
            return

        processing_msg = await message.answer(
            f"📄 <b>{filename}</b> o'qilmoqda... ({file_size//1024} KB)",
            parse_mode="HTML"
        )

        try:
            file = await bot.get_file(doc.file_id)
            file_io = await bot.download_file(file.file_path)
            file_bytes = file_io.read()

            await bot.edit_message_text(
                "🤖 AI mahsulotlarni ajratmoqda...",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )

            result = await process_price_list(file_bytes, filename, mime_type)

            if not result.get("ok"):
                await bot.edit_message_text(
                    "❌ Mahsulotlar topilmadi. Fayl to'g'ri price-list ekanligini tekshiring.",
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id
                )
                return

            products = result["products"]
            count = result["count"]
            source = result["source"]

            list_id = f"pl_{uid}_{int(asyncio.get_event_loop().time())}"
            product_cache[list_id] = {
                "products": products,
                "seller_uid": uid,
                "uploaded": 0,
                "skipped": 0,
            }

            preview = ""
            for i, p in enumerate(products[:5]):
                price = f"{p['price_uzs']:,} so'm" if p['price_uzs'] else "narx yo'q"
                preview += f"  {i+1}. {p['title'][:35]} — {price}\n"
            if count > 5:
                preview += f"  ... va yana {count-5} ta\n"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ Hammasi yuklash ({count} ta)",
                    callback_data=f"pl_all:{list_id}"
                )],
                [
                    InlineKeyboardButton(text="👁 Birma-bir", callback_data=f"pl_rev:{list_id}:0"),
                    InlineKeyboardButton(text="❌ Bekor", callback_data=f"pl_no:{list_id}"),
                ]
            ])

            with_v = result.get("with_variants", 0)
            without_v = result.get("without_variants", 0)
            variants_info = f"\n🔀 Variantli: {with_v} ta | Oddiy: {without_v} ta" if with_v else ""

            await bot.edit_message_text(
                f"✅ <b>{count} ta mahsulot topildi</b> ({source}){variants_info}\n\n"
                f"<b>Namuna:</b>\n{preview}\nQanday yuklaymiz?",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Document xatolik: {e}")
            await bot.edit_message_text(
                f"❌ Xatolik: {str(e)[:200]}",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )

    @dp.callback_query(F.data.startswith("pl_all:"))
    async def pl_all(call: CallbackQuery):
        list_id = call.data.split(":", 1)[1]
        data = product_cache.get(list_id)
        if not data:
            await call.answer("⚠️ Topilmadi.", show_alert=True)
            return

        await call.answer("⏳ Yuklanmoqda...")
        products = data["products"]
        seller_uid = data["seller_uid"]
        count = len(products)
        uploaded = 0
        failed = 0

        msg = await call.message.edit_text(f"⏳ Yuklanmoqda: 0/{count}...")

        for i, product in enumerate(products):
            try:
                product["seller_uid"] = seller_uid
                result = await upload_to_xazdent(product, bot=bot)
                if result.get("ok"):
                    uploaded += 1
                else:
                    failed += 1
                if (i + 1) % 5 == 0 or i == count - 1:
                    await bot.edit_message_text(
                        f"⏳ {i+1}/{count} | ✅ {uploaded} | ❌ {failed}",
                        chat_id=call.message.chat.id,
                        message_id=msg.message_id
                    )
                await asyncio.sleep(0.5)
            except Exception as e:
                failed += 1
                logger.error(f"[{i}] {e}")

        product_cache.pop(list_id, None)
        await bot.edit_message_text(
            f"🎉 <b>Tayyor!</b>\n\n✅ Yuklandi: <b>{uploaded}</b> ta\n❌ Xatolik: <b>{failed}</b> ta\n\n🌍 @XazdentBot da ko'rinadi",
            chat_id=call.message.chat.id,
            message_id=msg.message_id,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("pl_rev:"))
    async def pl_rev(call: CallbackQuery):
        parts = call.data.split(":")
        list_id = parts[1]
        index = int(parts[2])
        data = product_cache.get(list_id)
        if not data:
            await call.answer("⚠️ Topilmadi.", show_alert=True)
            return
        await call.answer()
        products = data["products"]
        count = len(products)
        if index >= count:
            product_cache.pop(list_id, None)
            await call.message.edit_text(
                f"✅ Hammasi ko'rildi!\n✅ Yuklandi: {data.get('uploaded',0)} ta\n⏭ O'tkazildi: {data.get('skipped',0)} ta"
            )
            return
        p = products[index]
        price_str = f"{p['price_uzs']:,} so'm" if p['price_uzs'] else "❓ narx yo'q"
        variants = ", ".join(str(v) for v in p.get("variants", [])[:4])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yuklash", callback_data=f"pl_ok:{list_id}:{index}"),
                InlineKeyboardButton(text="⏭ O'tkazish", callback_data=f"pl_skip:{list_id}:{index}"),
            ],
            [
                InlineKeyboardButton(text="✅ Qolganini hammasi", callback_data=f"pl_rest:{list_id}:{index}"),
                InlineKeyboardButton(text="❌ To'xtatish", callback_data=f"pl_no:{list_id}"),
            ]
        ])
        await call.message.edit_text(
            f"📦 <b>{index+1}/{count}</b>\n\n"
            f"✅ <b>{p['title']}</b>\n"
            f"💰 {price_str}\n"
            f"📝 {p.get('description','')[:80]}\n"
            f"{'📐 ' + variants if variants else ''}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("pl_ok:"))
    async def pl_ok(call: CallbackQuery):
        parts = call.data.split(":")
        list_id = parts[1]
        index = int(parts[2])
        data = product_cache.get(list_id)
        if not data:
            await call.answer("⚠️ Topilmadi.", show_alert=True)
            return
        product = data["products"][index]
        product["seller_uid"] = data["seller_uid"]
        result = await upload_to_xazdent(product, bot=bot)
        if result.get("ok"):
            data["uploaded"] = data.get("uploaded", 0) + 1
            await call.answer(f"✅ {result.get('article_code','')}")
        else:
            await call.answer(f"❌ {result.get('error','')[:50]}", show_alert=True)
        # Keyingi mahsulot
        await pl_rev_direct(call, list_id, index + 1)

    @dp.callback_query(F.data.startswith("pl_skip:"))
    async def pl_skip(call: CallbackQuery):
        parts = call.data.split(":")
        list_id = parts[1]
        index = int(parts[2])
        data = product_cache.get(list_id)
        if not data:
            await call.answer()
            return
        data["skipped"] = data.get("skipped", 0) + 1
        await call.answer("⏭")
        await pl_rev_direct(call, list_id, index + 1)

    async def pl_rev_direct(call, list_id, index):
        data = product_cache.get(list_id)
        if not data:
            return
        products = data["products"]
        count = len(products)
        if index >= count:
            product_cache.pop(list_id, None)
            await call.message.edit_text(
                f"✅ Hammasi!\n✅ Yuklandi: {data.get('uploaded',0)}\n⏭ O'tkazildi: {data.get('skipped',0)}"
            )
            return
        p = products[index]
        price_str = f"{p['price_uzs']:,} so'm" if p['price_uzs'] else "❓ narx yo'q"
        variants = ", ".join(str(v) for v in p.get("variants", [])[:4])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yuklash", callback_data=f"pl_ok:{list_id}:{index}"),
                InlineKeyboardButton(text="⏭ O'tkazish", callback_data=f"pl_skip:{list_id}:{index}"),
            ],
            [
                InlineKeyboardButton(text="✅ Qolganini hammasi", callback_data=f"pl_rest:{list_id}:{index}"),
                InlineKeyboardButton(text="❌ To'xtatish", callback_data=f"pl_no:{list_id}"),
            ]
        ])
        await call.message.edit_text(
            f"📦 <b>{index+1}/{count}</b>\n\n"
            f"✅ <b>{p['title']}</b>\n"
            f"💰 {price_str}\n"
            f"{'📐 ' + variants if variants else ''}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("pl_rest:"))
    async def pl_rest(call: CallbackQuery):
        parts = call.data.split(":")
        list_id = parts[1]
        from_idx = int(parts[2])
        data = product_cache.get(list_id)
        if not data:
            await call.answer("⚠️ Topilmadi.", show_alert=True)
            return
        await call.answer("⏳")
        remaining = data["products"][from_idx:]
        seller_uid = data["seller_uid"]
        uploaded = 0
        msg = await call.message.edit_text(f"⏳ {len(remaining)} ta yuklanmoqda...")
        for product in remaining:
            product["seller_uid"] = seller_uid
            result = await upload_to_xazdent(product, bot=bot)
            if result.get("ok"):
                uploaded += 1
            await asyncio.sleep(0.5)
        product_cache.pop(list_id, None)
        await bot.edit_message_text(
            f"🎉 <b>Tayyor!</b>\n✅ {uploaded} ta yuklandi\n🌍 @XazdentBot da ko'rinadi",
            chat_id=call.message.chat.id,
            message_id=msg.message_id,
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("pl_no:"))
    async def pl_no(call: CallbackQuery):
        list_id = call.data.split(":", 1)[1]
        product_cache.pop(list_id, None)
        await call.answer("Bekor")
        await call.message.edit_text("❌ Bekor qilindi.")
