# -*- coding: utf-8 -*-
"""Imzolangan WEB sessiya tokeni — botlar ham yasashi uchun alohida modul.

Nega kerak: sotuvchi bot tugmasiдан kabinet ochilganда havolaда `wtok` bo'lsa,
server sessiyani domen cookie'сига yozadi (`.xazdent.uz`) va sotuvchi
BOSHQA QAYTA LOGIN QILMAYDI (brauzerда ham).

Sir `BOT_TOKEN` (xaridor bot) dан hosil qilinadi — server tomonidа
`app/web/server.py:_WEB_SECRET` bilan AYNAN BIR XIL. Hamkor bot repoсида ham
shu modul BUYER_BOT_TOKEN ishlatadi — qiymati backenddagi BOT_TOKEN bilan bir xil.
"""
import base64
import hashlib
import hmac
import time

from app.config import BUYER_BOT_TOKEN as _TOK

WEB_TTL = 30 * 24 * 3600          # 30 kun — server bilan bir xil
_SECRET = hashlib.sha256(("xz-web-v1:" + (_TOK or "")).encode()).digest()


def make_web_token(user_id, jti: str = "") -> str:
    """`uid.exp.jti` + HMAC → base64url (server _verify_web_token bilan mos).

    jti bo'sh bo'lsa — sessiya jadvaliда yozuv talab qilinmaydi (server
    `if jti:` shartiда tekshiradi), ya'ni bot yasagan token darhol amal qiladi.
    """
    exp = int(time.time()) + WEB_TTL
    msg = f"{int(user_id)}.{exp}.{jti}".encode()
    sig = hmac.new(_SECRET, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + b"." + sig).decode().rstrip("=")


def cabinet_url(base: str, uid) -> str:
    """Sotuvchi kabineti havolasi — uid + imzolangan wtok bilan."""
    base = (base or "").rstrip("/")
    return f"{base}/?uid={int(uid)}&wtok={make_web_token(uid)}"
