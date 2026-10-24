# -*- coding: utf-8 -*-
"""👥 Hamkor bot qaysi guruhlarda ekanini eslab qoladi + hamkorlik arizalari guruhini bog'laydi.

Telegram bot «qaysi guruhlardaman» ro'yxatini bermaydi — faqat kelgan update'lardan
bilish mumkin. Shuning uchun guruhdan kelgan har bir xabar / a'zolik o'zgarishi
`settings.hamkor_bot_guruhlar` ga yoziladi ({id: nom}).

Hamkorlik arizalari (hamkor.xazdent.uz) guruhi `settings.hamkor_ariza_chat_id`:
  • nomida «shartnoma» bo'lgan guruh — avtomatik (agar hali bog'lanmagan bo'lsa);
  • admin guruhda /start yoki /arizaguruh yozsa — o'sha guruh.
"""
import json
import logging

from aiogram.types import ChatMemberUpdated

from app.database import get_setting, update_setting
from app.runtime import router

log = logging.getLogger(__name__)
ROYXAT = "hamkor_bot_guruhlar"
ARIZA = "hamkor_ariza_chat_id"
_KESH = {}


async def eslab_qol(chat):
    """Guruhni ro'yxatga yozadi; «shartnoma» guruhini (bog'lanmagan bo'lsa) arizaga bog'laydi.
    → True agar ariza guruhi SHU chaqiriqda bog'langan bo'lsa."""
    if chat is None or chat.type not in ("group", "supergroup"):
        return False
    cid, nom = int(chat.id), (chat.title or "")
    if _KESH.get(cid) == nom:
        return False
    _KESH[cid] = nom
    try:
        royxat = json.loads((await get_setting(ROYXAT)) or "{}")
    except Exception:
        royxat = {}
    if royxat.get(str(cid)) != nom:
        royxat[str(cid)] = nom
        await update_setting(ROYXAT, json.dumps(royxat, ensure_ascii=False))
        log.info("guruh eslab qolindi: %s %s", cid, nom)
    if "shartnoma" in nom.lower() and not str((await get_setting(ARIZA)) or "").strip():
        await update_setting(ARIZA, str(cid))
        log.info("hamkorlik arizalari guruhi avtomatik bog'landi: %s %s", cid, nom)
        return True
    return False


async def _kuzat(handler, event, data):
    try:
        if await eslab_qol(getattr(event, "chat", None)):
            try:
                await event.answer("✅ Hamkorlik arizalari (hamkor.xazdent.uz) endi shu guruhga tushadi.")
            except Exception:
                pass
    except Exception as e:
        log.warning("guruh kuzatuvi xato: %s", e)
    return await handler(event, data)


router.message.outer_middleware(_kuzat)


@router.my_chat_member()
async def bot_azoligi(event: ChatMemberUpdated):
    """Bot guruhga qo'shilsa / admin qilinsa — darhol eslab qolamiz."""
    try:
        if event.new_chat_member.status in ("member", "administrator"):
            if await eslab_qol(event.chat):
                await event.bot.send_message(event.chat.id, "✅ Hamkorlik arizalari (hamkor.xazdent.uz) endi shu guruhga tushadi.")
    except Exception as e:
        log.warning("my_chat_member xato: %s", e)
