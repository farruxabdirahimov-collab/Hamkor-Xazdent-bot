# -*- coding: utf-8 -*-
"""DL — Hamkor bot `/start <kod>` javobi: kabinet (Mini App) AYNAN kerakli bo'limda ochiladi.

Kodlar (app/deeplink.py — xazdent-backend dagi bilan bir xil nusxa):
  h-<bo'lim>  kabinet bo'limi (bugun, buyurtma, mahsulot, aksiya, mijozlar, profilim, sahifa, ulashish,
              tolov, dokon, profil)
  ho<id>      buyurtma kartochkasi          hp<id>  mahsulot tahriri
Kabinetga kirish — faqat login/parol (yoki SMS) — tugma tokensiz; kirgandan keyin shu bo'lim ochiladi
(webapp/mvp/c-kabinet.js C.dlOch). Parametrli /start panel sessiyalarini YOPMAYDI (oddiy /start yopadi):
havola faqat kabinetni ochadi, hech narsani tasdiqlamaydi.
"""
from __future__ import annotations

import logging

from app import deeplink as dl

log = logging.getLogger(__name__)

_MATN = {
    "h_bolim": "🏪 *Hamkor kabineti*\n\nKerakli bo'lim pastdagi tugmada 👇",
    "h_buyurtma": "📦 *Buyurtma #%s*\n\nKabinetda ochish uchun pastdagi tugmani bosing 👇",
    "h_mahsulot": "✏️ *Mahsulot tahriri*\n\nKabinetda ochish uchun pastdagi tugmani bosing 👇",
}


def _kb(matn: str, url: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=matn, web_app=WebAppInfo(url=url))]])


def javob_matni(d: dict, ulangan: bool) -> str:
    t = _MATN.get(d["tur"], _MATN["h_bolim"])
    if "%s" in t:
        t = t % d.get("id")
    if not ulangan:
        t += ("\n\n🔐 Kabinetga *login va parolingiz* (yoki telefon + SMS) bilan kiring — "
              "kirgandan keyin shu sahifa ochiladi.")
    return t


async def hamkor_javob(msg, d: dict, hamkor_url: str, ulangan: bool) -> None:
    """`/start <kod>` (Hamkor). d = dl.ochish(kod, 'hamkor')."""
    url = dl.webapp_url(d, hamkor_url)
    if not url:
        await msg.answer("🏪 Hamkor kabineti hozircha mavjud emas. Keyinroq urinib ko'ring.")
        return
    await msg.answer(javob_matni(d, ulangan), reply_markup=_kb(d["tugma"], url))
