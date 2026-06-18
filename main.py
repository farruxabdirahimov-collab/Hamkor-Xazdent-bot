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


async def main():
    await get_pool()   # umumiy bazaga ulanishni tekshiramiz
    dp.include_router(router)
    log.info("🏪 XazDent SOTUVCHI bot ishga tushdi!")
    xlog.notify("🏪 XazDent Sotuvchi bot ishga tushdi", "INFO")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
