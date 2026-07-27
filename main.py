# -*- coding: utf-8 -*-
"""XazDent SOTUVCHI bot — kirish nuqtasi.

Xaridor bot (xazdent-backend) bilan BIR XIL Postgres bazadan foydalanadi.
Sxema xaridor bot tomonidan yaratiladi (init_db) — bu yerda faqat ulanamiz.
Xaridorlarga xabar buyer_bot (BUYER_BOT_TOKEN) orqali yuboriladi.
"""
import asyncio
import logging

from app.config import BOT_TOKEN
from app.runtime import bot, dp, router
from app.database import get_pool
import app.handlers  # noqa: F401  — barcha handlerlarni ro'yxatga oladi
from app import logger as xlog

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Markaziy logger (xatolar + hodisalar log-guruhga)
xlog.setup()


@dp.errors()
async def _on_error(event):
    try:
        exc = event.exception
        await xlog.send_log(f"Sotuvchi bot update xato: {type(exc).__name__}: {exc}", "ERROR")
    except Exception:
        pass
    return True


# DEV: sotuvchi botga yozgan har kim SINOVCHI (prod'da hech narsa qilmaydi)
try:
    from app import stage as _stg
    dp.message.outer_middleware(_stg.tester_middleware())
    dp.callback_query.outer_middleware(_stg.tester_middleware())
except Exception as _me:
    log.error(f"tester middleware xato: {_me}")


async def main():
    await get_pool()   # umumiy bazaga ulanishni tekshiramiz
    # BOSQICH tekshiruvi: dev servis PROD bazasiga ulanib qolmasin
    try:
        from app import stage as _stage
        await _stage.db_marker_check()
        if _stage.IS_DEV:
            _n = await _stage.load_testers()
            log.warning("DEV: %s sinovchi yuklandi", _n)
            _dc = "bor" if _stage.DEV_CHAT_ID else "YOQ (xabarlar yuborilmaydi)"
            log.warning("DEV REJIMI: chiqish xabarlari dev guruhiga yonaltiriladi, DEV_CHAT_ID=%s", _dc)
    except Exception as _se:
        log.error(f"stage tekshiruvi xato: {_se}")
    dp.include_router(router)
    # hamkor.xazdent.uz uchun web-proxy (port 8080) — sotuvchi botga parallel
    try:
        from proxy import start_web
        await start_web()
    except Exception as e:
        log.error(f"web proxy ishga tushmadi: {e}")
    log.info("🏪 XazDent SOTUVCHI bot ishga tushdi!")
    xlog.notify("🏪 XazDent Sotuvchi bot ishga tushdi", "INFO")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
