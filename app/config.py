# -*- coding: utf-8 -*-
"""Sotuvchi (hamkor) bot konfiguratsiyasi.

XAZDENT ikki botli: xaridor bot (xazdent-backend) + sotuvchi bot (shu repo).
Ikkalasi BIR XIL Postgres bazadan foydalanadi (DATABASE_URL).

Tokenlar:
  BOT_TOKEN        — SHU bot (sotuvchi/hamkor) tokeni
  BUYER_BOT_TOKEN  — xaridor botning tokeni (xaridorlarga xabar yuborish uchun)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram / muhit ──────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN")                  # sotuvchi bot
BUYER_BOT_TOKEN = os.getenv("BUYER_BOT_TOKEN", "").strip()  # xaridor bot (cross-notify)
CHANNEL_ID      = os.getenv("CHANNEL_ID", "@xazdent")
ADMIN_IDS       = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBAPP_URL      = os.getenv("WEBAPP_URL", "").rstrip("/")
# 🏪 Sotuvchi kabineti DOMENI (xazdent.uz/hamkor emas — alohida subdomen).
# Env bilan almashtirish mumkin; bo'sh bo'lsa WEBAPP_URL/hamkor ishlatiladi.
HAMKOR_URL = os.getenv("HAMKOR_URL", "https://hamkor.xazdent.uz").rstrip("/")

# MVP:H — yangi model (sotuvchining o'z kassasi). `XAZ_MODEL=v1` — eski model qaytadi.
# Asosiy backend bilan bir xil o'zgaruvchi (backend app/mvp.py da ham shunday).
XAZ_MODEL = (os.getenv("XAZ_MODEL") or "mvp").strip().lower()


def mvp_rejim() -> bool:
    return XAZ_MODEL == "mvp"


# MVP:H — asosiy backend ichki API'si (buyurtma amallari, /tugadi, /bor).
# BACKEND_URL bo'lmasa — mavjud WEB_UPSTREAM (hamkor proxy ham shu backendga boradi).
BACKEND_URL = (os.getenv("BACKEND_URL") or os.getenv("WEB_UPSTREAM")
               or "https://xazdent-bot-production.up.railway.app").rstrip("/")
ICHKI_KALIT = (os.getenv("ICHKI_KALIT") or "").strip()


# Repo ildizi
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Reklama e'lon narxlari (ball) ─────────────────────────────────────────────
AD_PRICE_TOSHKENT = 200
AD_PRICE_REGION   = 50
AD_PRICE_BOTH_AUD = 2
AD_REGION_PRICES  = {"Toshkent shahri": 200}
AD_REGION_DEFAULT = 50
