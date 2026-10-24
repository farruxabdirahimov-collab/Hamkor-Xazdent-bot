# -*- coding: utf-8 -*-
"""Markaziy logger — barcha xazdent loyihalari loglarini bitta logger-bot
orqali bitta log-guruhga yuboradi. Asosan xatoliklar + muhim hodisalar.

Boshqa loyihalar (masalan Hamkor-Xazdent-bot) ham shu modulni nusxalab,
bir xil LOGGER_BOT_TOKEN + LOG_GROUP_ID bilan ulansa, hammasi bitta guruhga tushadi.

Env:
  LOGGER_BOT_TOKEN  — log yuboruvchi ALOHIDA bot tokeni (@BotFather'dan)
  LOG_GROUP_ID      — loglar tushadigan guruh chat_id (masalan -1001234567890)
  PROJECT_NAME      — loyiha nomi (loglar shu nom bilan belgilanadi)
"""
import os
import time
import asyncio
import logging

LOGGER_BOT_TOKEN = os.getenv("LOGGER_BOT_TOKEN", "").strip()
LOG_GROUP_ID     = os.getenv("LOG_GROUP_ID", "").strip()
PROJECT_NAME     = os.getenv("PROJECT_NAME", "xazdent-backend").strip()

_ICON = {"INFO": "ℹ️", "NEW": "🆕", "WARN": "⚠️", "ERROR": "🔴", "EVENT": "📌", "ORDER": "🛒"}
_recent = {}   # dedupe: (level, text) -> oxirgi yuborilgan vaqt


def _enabled():
    return bool(LOGGER_BOT_TOKEN and LOG_GROUP_ID)


async def send_log(text, level="INFO"):
    """Log xabarini log-guruhga yuboradi. Hech qachon istisno ko'tarmaydi."""
    if not _enabled():
        return
    now = time.time()
    key = (level, (text or "")[:120])
    if now - _recent.get(key, 0) < 30:   # bir xil xabar 30s ichida takrorlanmasin (spam/loop himoyasi)
        return
    _recent[key] = now
    body = f"{_ICON.get(level, 'ℹ️')} [{PROJECT_NAME}] {level}\n{text}"
    # 🧪 DEV: loglar PROD log-guruhига TUSHMASIN (u yerда haqiqiy buyurtmalar
    # kuzatiladi — dev sinovlari aralashса chalkashadi). Dev'да manzil
    # DEV_CHAT_ID; u berilmagan bo'lsa umuman yuborilmaydi.
    target = LOG_GROUP_ID
    try:
        from app import stage as _stage
        if _stage.IS_DEV:
            if not _stage.DEV_CHAT_ID:
                return
            target = _stage.DEV_CHAT_ID
            body = f"🧪 {_stage.DEV_LABEL}\n{body}"
    except Exception:
        pass
    if len(body) > 3900:
        body = body[:3900] + "…"
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"https://api.telegram.org/bot{LOGGER_BOT_TOKEN}/sendMessage",
                json={"chat_id": target, "text": body,
                      "disable_web_page_preview": True},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception:
        pass   # logger ilovani hech qachon buzmasin


def notify(text, level="INFO"):
    """Sync yoki async kontekstdan fire-and-forget log yuborish."""
    if not _enabled():
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send_log(text, level))
    except RuntimeError:
        pass   # ishlayotgan event loop yo'q — o'tkazib yuboramiz


class TelegramLogHandler(logging.Handler):
    """ERROR+ darajadagi loglarni log-guruhga uzatadi —
    kоddagi mavjud log.error/log.exception larni avtomatik tutadi."""
    # O'tkinchi polling/tarmoq xatolari — log-guruhga YUBORILMAYDI (o'zi tiklanadi, shovqin)
    _SKIP = ("failed to fetch updates", "flood control", "retry after", "retryafter",
             "bad gateway", "telegramservererror", "telegramnetworkerror",
             "timed out", "connection reset", "temporary failure", "conflict: terminated")

    def emit(self, record):
        try:
            if record.levelno < logging.ERROR:
                return
            msg = record.getMessage()
            _low = (msg or "").lower()
            if any(s in _low for s in self._SKIP):
                return
            if record.exc_info:
                import traceback
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info))[:1500]
            loc = f"{record.name} ({record.module}:{record.lineno})"
            notify(f"{loc}\n{msg}", "ERROR")
        except Exception:
            pass


def setup(level=logging.ERROR):
    """Root loggerga handler ulaydi — barcha ERROR+ loglar guruhga ketadi."""
    if not _enabled():
        return
    h = TelegramLogHandler()
    h.setLevel(level)
    logging.getLogger().addHandler(h)
