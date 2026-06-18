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

# Repo ildizi
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Reklama e'lon narxlari (ball) ─────────────────────────────────────────────
AD_PRICE_TOSHKENT = 200
AD_PRICE_REGION   = 50
AD_PRICE_BOTH_AUD = 2
AD_REGION_PRICES  = {"Toshkent shahri": 200}
AD_REGION_DEFAULT = 50
