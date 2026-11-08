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
# 🌐 Foydalanuvchiga boradigan havolalar bazasi. PROD env'da WEBAPP_URL = Railway ichki domeni
# (`*.up.railway.app`) — u O'zbekistonda SNI bo'yicha BLOKLANGAN: bot yuborgan «Buyurtmani ochish» va
# boshqa havolalar mijozda ochilmasdi (2026-11-07). Shuning uchun railway domeni bo'lsa — Cloudflare'dagi
# o'z domenimiz: env XAZ_SAYT_URL, bo'lmasa PROD → https://xazdent.uz, DEV → https://dev.xazdent.uz.
# Xom qiymat WEBAPP_URL_XOM da — tashqi xizmatda ro'yxatdan o'tgan callback/redirect manzillari uchun.
WEBAPP_URL_XOM = os.getenv("WEBAPP_URL", "").rstrip("/")


def _ommaviy_url(u: str) -> str:
    if not u or ".railway.app" not in u:
        return u
    o = (os.getenv("XAZ_SAYT_URL") or "").strip().rstrip("/")
    if o.startswith("https://") and ".railway.app" not in o:
        return o
    bosqich = (os.getenv("APP_STAGE") or "prod").strip().lower()
    dev = bosqich in ("dev", "development", "develop", "staging", "stage", "test") or "-development." in u
    return "https://dev.xazdent.uz" if dev else "https://xazdent.uz"


WEBAPP_URL = _ommaviy_url(WEBAPP_URL_XOM)
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
# Avval ICHKI_KALIT, bo'lmasa ikkala servisda bor INTERNAL_API_KEY (backend app/ichki_kalit.py ham shunday).
ICHKI_KALIT = ((os.getenv("ICHKI_KALIT") or "").strip()
               or (os.getenv("INTERNAL_API_KEY") or "").strip())


# Repo ildizi
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Reklama e'lon narxlari (ball) ─────────────────────────────────────────────
AD_PRICE_TOSHKENT = 200
AD_PRICE_REGION   = 50
AD_PRICE_BOTH_AUD = 2
AD_REGION_PRICES  = {"Toshkent shahri": 200}
AD_REGION_DEFAULT = 50
