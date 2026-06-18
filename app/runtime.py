# -*- coding: utf-8 -*-
"""Sotuvchi bot ish vaqti singletonlari: bot (sotuvchi), dp, router + buyer_bot.

`bot`       — SHU (sotuvchi) bot. Sotuvchilarga xabar shu orqali.
`buyer_bot` — xaridor bot instansiyasi. Xaridorlarga (taklif/buyurtma holati)
              xabar SHU orqali yuboriladi (botlararo xabarlashish).
"""
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import BOT_TOKEN, BUYER_BOT_TOKEN

bot    = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp     = Dispatcher(storage=MemoryStorage())
router = Router()

# Xaridor botga xabar yuborish uchun. Token bo'lsa — alohida instansiya;
# bo'lmasa (lokal/test) — sotuvchi botga fallback (try/except ichida jim o'tadi).
# Faqat chiqish chaqiruvlari uchun (send_message/...), polling qilinmaydi.
buyer_bot = (Bot(token=BUYER_BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
             if BUYER_BOT_TOKEN else bot)
