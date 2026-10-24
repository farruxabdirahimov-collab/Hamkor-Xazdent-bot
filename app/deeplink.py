# -*- coding: utf-8 -*-
"""DL — Telegram bot orqali ulashish havolalari (deep link). YAGONA manba.

Bitta qisqa kod (Telegram start parametri: faqat [A-Za-z0-9_-], ≤ 64 belgi) ikki botda ham
kerakli sahifani ochadi:
    https://t.me/<bot>?start=<kod>            — DOIM ishlaydi: bot javobida Mini App tugmasi
    https://t.me/<bot>?startapp=<kod>         — Mini App'ni TO'G'RIDAN ochadi (BotFather «Main Mini App»)
    https://t.me/<bot>/<app>?startapp=<kod>   — /newapp bilan yaratilgan Mini App (qisqa nom)
(b) turi env `TG_BOT_APP_XARIDOR` / `TG_BOT_APP_HAMKOR` (= 'main' yoki app qisqa nomi) bo'lsa ishlatiladi.

Kod grammatikasi:  <nishon>[__<src>][__r-<ref>]
  Xaridor (@XazdentBot, Mini App = catalog.html):
    s<id>      do'kon (ASOSIY) → /shop/<id>: nashr qilingan+slug → vitrina /<slug>, aks holda SPA do'kon sahifasi
    d-<slug>   do'kon vitrinasi /<slug> (faqat nashr qilingan do'kon uchun ma'noli)
    p<id>      mahsulot /product/<id>            o<id>   buyurtma /orders/<id> (kirish kerak)
    k<id>      toifa (katalog filtri)            cart    savat           fav  sevimlilar (kirish)
    orders     buyurtmalarim (kirish)            dokonlar  do'konlar     bosh bosh sahifa
  Hamkor (@hamkorXazdentbot, Mini App = hamkor.html):
    h-<bo'lim> kabinet bo'limi (bugun, buyurtma, mahsulot, aksiya, mijozlar, profilim, sahifa,
               ulashish, tolov, dokon, profil)
    ho<id>     buyurtma kartochkasi              hp<id>  mahsulot tahriri
  Qo'shimchalar (ixtiyoriy, tartib muhim emas):
    __<src>    manba (app.mvp_manba bilan bir xil kodlar: tg, ig, wa, qr, sms, nusxa, tg_<kanal> …)
    __r-<ref>  taklif qiluvchining ref kodi (app.mvp_voronka.ref_kod_ol) — `?ref=` bilan bir xil
Noto'g'ri qo'shimcha e'tiborsiz qoldiriladi; noto'g'ri nishon → None (bosh sahifa).

JS ekvivalenti: webapp/mvp/deeplink.js (XzDeeplink.ochish/kodla) — qoidalar AYNAN bir xil.
Hamkor bot repo'sida shu faylning nusxasi bor (app/deeplink.py) — o'zgarsa ikkalasini yangila.
Sof funksiyalar (DB/tarmoq yo'q); faqat `bot_nomi()` runtime'dan getMe qiladi (keshlab).
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlencode

__all__ = ["MAKS", "kodla", "dokon_kodi", "ochish", "bot_havola", "havolalar", "app_nomi",
           "webapp_url", "bot_nomi", "bot_nomi_qoy", "HAMKOR_BOLIM", "TUGMA"]

MAKS = 64
_ID = r"[1-9][0-9]{0,9}"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")       # app.mvp_dokon SLUG_YOL (kichik harf)
_SRC_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
_REF_RE = re.compile(r"^[a-z0-9]{5,12}$")                           # app.mvp_voronka ref_kod (31-lik alifbo)
_APP_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")
_BOT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_TG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Hamkor kabineti bo'limlari (webapp/mvp/c-kabinet.js MENYU) — qisqa nom → go() id
HAMKOR_BOLIM = {
    "bugun": "mvp-bugun", "statistika": "mvp-bugun",
    "buyurtma": "mvp-buyurtma", "buyurtmalar": "mvp-buyurtma",
    "mahsulot": "mvp-mahsulot", "mahsulotlar": "mvp-mahsulot",
    "aksiya": "mvp-aksiya", "aksiyalar": "mvp-aksiya",
    "mijozlar": "mvp-mijozlar", "profilim": "mvp-profilim", "sahifa": "mvp-sahifa",
    "ulashish": "mvp-ulashish", "tolov": "mvp-tolov", "dokon": "mvp-dokon", "profil": "mvp-profil",
}

# Tugma matni (bot javobi) — tur → (sarlavha, tugma)
TUGMA = {
    "dokon":       ("🏪 Do'kon sahifasi", "🏪 Do'konni ochish"),
    "mahsulot":    ("🦷 Mahsulot", "🛍 Mahsulotni ochish"),
    "buyurtma":    ("📦 Buyurtma", "📦 Buyurtmani ochish"),
    "toifa":       ("🗂 Toifa", "🗂 Toifani ochish"),
    "savat":       ("🛒 Savat", "🛒 Savatni ochish"),
    "sevimli":     ("❤️ Sevimlilar", "❤️ Sevimlilarni ochish"),
    "buyurtmalar": ("📦 Buyurtmalarim", "📦 Buyurtmalarni ochish"),
    "dokonlar":    ("🏬 Do'konlar", "🏬 Do'konlarni ochish"),
    "bosh":        ("🦷 XazDent Dental Market", "🛍 Katalogni ochish"),
    "h_bolim":     ("🏪 Hamkor kabineti", "🏪 Kabinetni ochish"),
    "h_buyurtma":  ("📦 Buyurtma", "📦 Buyurtmani ochish"),
    "h_mahsulot":  ("✏️ Mahsulot", "✏️ Mahsulotni ochish"),
}

# Xaridor: kalit so'z → (tur, yo'l, kirish kerakmi)
_SOZ = {
    "cart": ("savat", "/cart", False),
    "fav": ("sevimli", "/profile/favorites", True),
    "orders": ("buyurtmalar", "/orders", True),
    "dokonlar": ("dokonlar", "/dokonlar", False),
    "bosh": ("bosh", "/", False),
}
# kodla() uchun tur sinonimlari
_TUR = {"d": "d", "dokon": "d", "slug": "d", "s": "s", "dokon_id": "s", "shop": "s",
        "p": "p", "mahsulot": "p", "product": "p", "o": "o", "buyurtma": "o", "order": "o",
        "k": "k", "toifa": "k", "cat": "k", "h": "h", "bolim": "h", "ho": "ho", "hp": "hp",
        "cart": "cart", "savat": "cart", "fav": "fav", "sevimli": "fav", "orders": "orders",
        "buyurtmalar": "orders", "dokonlar": "dokonlar", "bosh": "bosh"}


def _src_tozala(src) -> str:
    s = str(src or "").strip().lower()
    if not s or "__" in s or s.startswith("r-") or s.endswith(("_", "-")) or not _SRC_RE.match(s):
        return ""
    return s


def _ref_tozala(ref) -> str:
    r = str(ref or "").strip().lower()
    return r if _REF_RE.match(r) else ""


def _id(v) -> int:
    try:
        n = int(str(v).strip())
    except Exception:
        return 0
    return n if 0 < n < 10 ** 10 else 0


def _qosh(nishon: str, src: str, ref: str) -> str:
    """Nishonga qo'shimchalar; 64 dan oshsa avval ref, keyin src tashlanadi."""
    for s, r in ((src, ref), (src, ""), ("", "")):
        k = nishon + ("__" + s if s else "") + ("__r-" + r if r else "")
        if len(k) <= MAKS:
            return k
    return nishon


def kodla(tur: str, qiymat=None, *, src=None, ref=None) -> str:
    """(tur, qiymat) → start parametri. Noto'g'ri kirish → ValueError.
    kodla('d', 'dentmed', src='ig') → 'd-dentmed__ig';  kodla('p', 15) → 'p15'."""
    t = _TUR.get(str(tur or "").strip().lower())
    if not t:
        raise ValueError("noma'lum tur: %r" % (tur,))
    if t == "d":
        slug = str(qiymat or "").strip().lower()
        if not _SLUG_RE.match(slug):
            raise ValueError("noto'g'ri slug: %r" % (qiymat,))
        nishon = "d-" + slug
    elif t in ("s", "p", "o", "k", "ho", "hp"):
        n = _id(qiymat)
        if not n:
            raise ValueError("noto'g'ri id: %r" % (qiymat,))
        nishon = t + str(n)
    elif t == "h":
        b = str(qiymat or "").strip().lower()
        if b.startswith("mvp-"):
            b = b[4:]
        if b not in HAMKOR_BOLIM:
            raise ValueError("noma'lum bo'lim: %r" % (qiymat,))
        nishon = "h-" + b
    else:
        nishon = t
    return _qosh(nishon, _src_tozala(src), _ref_tozala(ref))


def dokon_kodi(shop_id=None, slug=None, *, src=None, ref=None) -> str:
    """Do'kon havolasi kodi: ASOSIY — s<id> (slug bo'sh / vitrina nashr qilinmagan do'konlarda ham
    ishlaydi; Mini App nashr qilingan bo'lsa vitrinani, aks holda SPA do'kon sahifasini ochadi).
    id yo'q bo'lsa — d-<slug>. Ikkalasi ham yo'q → ''."""
    if _id(shop_id):
        return kodla("s", shop_id, src=src, ref=ref)
    s = str(slug or "").strip().lower()
    if _SLUG_RE.match(s):
        return kodla("d", s, src=src, ref=ref)
    return ""


def _nishon(n: str):
    """nishon → dict (src/ref'siz) yoki None."""
    m = re.fullmatch(r"d-([a-z0-9-]{3,40})", n)
    if m and _SLUG_RE.match(m.group(1)):
        s = m.group(1)
        return {"ilova": "xaridor", "tur": "dokon", "slug": s, "id": None, "yol": "/" + s,
                "tashqi": True, "kirish": False}
    m = re.fullmatch(r"(s|p|o|k|ho|hp)(" + _ID + ")", n)
    if m:
        h, i = m.group(1), int(m.group(2))
        if h == "s":
            return {"ilova": "xaridor", "tur": "dokon", "slug": None, "id": i, "yol": "/shop/%d" % i,
                    "tashqi": True, "kirish": False}
        if h == "p":
            return {"ilova": "xaridor", "tur": "mahsulot", "id": i, "yol": "/product/%d" % i,
                    "tashqi": False, "kirish": False}
        if h == "o":
            return {"ilova": "xaridor", "tur": "buyurtma", "id": i, "yol": "/orders/%d" % i,
                    "tashqi": False, "kirish": True}
        if h == "k":
            return {"ilova": "xaridor", "tur": "toifa", "id": i, "yol": "/products",
                    "tashqi": False, "kirish": False}
        if h == "ho":
            return {"ilova": "hamkor", "tur": "h_buyurtma", "id": i, "yol": "mvp-buyurtma",
                    "tashqi": False, "kirish": True}
        return {"ilova": "hamkor", "tur": "h_mahsulot", "id": i, "yol": "mvp-mahsulot",
                "tashqi": False, "kirish": True}
    m = re.fullmatch(r"h-([a-z]{3,20})", n)
    if m and m.group(1) in HAMKOR_BOLIM:
        return {"ilova": "hamkor", "tur": "h_bolim", "bolim": m.group(1), "id": None,
                "yol": HAMKOR_BOLIM[m.group(1)], "tashqi": False, "kirish": True}
    if n in _SOZ:
        tur, yol, kirish = _SOZ[n]
        return {"ilova": "xaridor", "tur": tur, "id": None, "yol": yol, "tashqi": False, "kirish": kirish}
    return None


def ochish(param, ilova: str = None):
    """start parametri → {ilova, tur, id, slug?, bolim?, yol, tashqi, kirish, src, ref, kod, sarlavha, tugma}
    yoki None (noto'g'ri / boshqa ilovaniki). `ilova` berilsa ('xaridor'|'hamkor') — faqat o'shaniki."""
    p = str(param or "").strip()
    if not _TG_RE.match(p):
        return None
    p = p.lower()
    qism = p.split("__")
    d = _nishon(qism[0])
    if not d or (ilova and d["ilova"] != ilova):
        return None
    src = ref = ""
    for q in qism[1:]:
        if q.startswith("r-"):
            if not ref:
                ref = _ref_tozala(q[2:])
        elif not src:
            src = _src_tozala(q)
    d.update(src=src, ref=ref, kod=p)
    d.setdefault("slug", None)
    d.setdefault("bolim", None)
    sar, tug = TUGMA.get(d["tur"], ("XazDent", "Ochish"))
    d.update(sarlavha=sar, tugma=tug)
    return d


# ═══ Havolalar ═══════════════════════════════════════════════════════════════
_STANDART_BOT = {"xaridor": "XazdentBot", "hamkor": "hamkorXazdentbot"}
_ENV_BOT = {"xaridor": "TG_BOT_XARIDOR", "hamkor": "TG_BOT_HAMKOR"}
_ENV_APP = {"xaridor": "TG_BOT_APP_XARIDOR", "hamkor": "TG_BOT_APP_HAMKOR"}
_BOT_KESH = {}
_BOT_XATO = {}


def app_nomi(ilova: str) -> str:
    """BotFather Mini App: 'main' (Main Mini App) | qisqa nom | '' (sozlanmagan → ?start=)."""
    v = (os.getenv(_ENV_APP.get(ilova, "")) or "").strip().strip("/")
    if v.lower() == "main":
        return "main"
    return v if _APP_RE.match(v) else ""


def bot_havola(kod: str, bot: str, app: str = "") -> str:
    """kod → t.me havola. app='' → ?start= (bot javobi orqali), 'main' → ?startapp=, aks holda /<app>?startapp=."""
    bot = str(bot or "").strip().lstrip("@")
    if not _TG_RE.match(kod or "") or not bot:
        return ""
    if app == "main":
        return "https://t.me/%s?startapp=%s" % (bot, kod)
    if app:
        return "https://t.me/%s/%s?startapp=%s" % (bot, app, kod)
    return "https://t.me/%s?start=%s" % (bot, kod)


def havolalar(kod: str, ilova: str = "xaridor", bot: str = None) -> dict:
    """{kod, bot, start (doim ishlaydi), startapp ('' — sozlanmagan), havola (afzal: startapp bo'lsa u)}."""
    b = bot or bot_nomi_sinx(ilova)
    a = app_nomi(ilova)
    start = bot_havola(kod, b, "")
    sa = bot_havola(kod, b, a) if a else ""
    return {"kod": kod, "bot": b, "start": start, "startapp": sa, "havola": sa or start}


def webapp_url(d: dict, base: str, *, uid=None, wtok: str = "", role: str = "clinic", yol: str = None) -> str:
    """Bot tugmasi (WebAppInfo) uchun URL — Mini App AYNAN shu sahifada ochiladi.
    Xaridor vitrina (tashqi): base/<slug>?src=..&ref=..[&uid&wtok] (server ochilishni manba bilan yozadi).
    Xaridor SPA: base/catalog?startapp=<kod>[&uid&role&wtok] (catalog.html routeri yo'lga o'tadi).
    Hamkor: base/?kirish=1&startapp=<kod> (kabinet login/parol bilan; token qo'shilmaydi).
    `yol` — tashqi sahifa yo'lini almashtirish (s<id>: bot bazadan bilsa — nashr qilingan vitrina /<slug>)."""
    base = str(base or "").rstrip("/")
    if not base or not d:
        return ""
    if d["ilova"] == "hamkor":
        # kirish=1 — kirmagan sotuvchiga «Hamkor bo'lish» landingi emas, kirish formasi (keyin shu bo'lim)
        return base + "/?" + urlencode({"kirish": "1", "startapp": d["kod"]})
    q = []
    if d.get("tashqi"):
        q.append(("src", d.get("src") or "tgbot"))
        if d.get("ref"):
            q.append(("ref", d["ref"]))
        if uid and wtok:
            q += [("uid", str(uid)), ("wtok", wtok)]
        return base + (yol or d["yol"]) + "?" + urlencode(q)
    q.append(("startapp", d["kod"]))
    if uid:
        q += [("uid", str(uid)), ("role", role or "clinic")]
        if wtok:
            q.append(("wtok", wtok))
    return base + "/catalog?" + urlencode(q)


def bot_nomi_qoy(ilova: str, nom: str) -> None:
    nom = str(nom or "").strip().lstrip("@")
    if _BOT_RE.match(nom):
        _BOT_KESH[ilova] = nom


def bot_nomi_sinx(ilova: str) -> str:
    """env → kesh (getMe) → standart. Tarmoqsiz."""
    v = (os.getenv(_ENV_BOT.get(ilova, "")) or "").strip().lstrip("@")
    if _BOT_RE.match(v):
        return v
    return _BOT_KESH.get(ilova) or _STANDART_BOT.get(ilova, "")


async def bot_nomi(ilova: str) -> str:
    """Bot @username (DEV va PROD da har xil). env TG_BOT_XARIDOR/TG_BOT_HAMKOR ustun; aks holda
    runtime botidan getMe (bir marta, keshlanadi). Backend: bot=xaridor, seller_bot=hamkor;
    Hamkor bot repo: bot=hamkor, buyer_bot=xaridor."""
    v = (os.getenv(_ENV_BOT.get(ilova, "")) or "").strip().lstrip("@")
    if _BOT_RE.match(v):
        return v
    if ilova in _BOT_KESH:
        return _BOT_KESH[ilova]
    import time as _t
    if _t.time() - _BOT_XATO.get(ilova, 0) < 300:          # yaqinda getMe xato berdi — qayta urinmaymiz
        return _STANDART_BOT.get(ilova, "")
    import sys as _sys
    rt = _sys.modules.get("app.runtime")
    if rt is None:                    # runtime yuklanmagan (test / skript) — tarmoqqa chiqmaymiz
        return _STANDART_BOT.get(ilova, "")
    try:
        if hasattr(rt, "seller_bot"):
            b = rt.bot if ilova == "xaridor" else (rt.seller_bot if rt.seller_bot is not rt.bot else None)
        else:
            b = getattr(rt, "buyer_bot", None) if ilova == "xaridor" else rt.bot
            if ilova == "xaridor" and b is rt.bot:
                b = None
        if b is not None:
            me = await b.get_me()
            bot_nomi_qoy(ilova, getattr(me, "username", ""))
    except Exception:
        _BOT_XATO[ilova] = _t.time()
    return _BOT_KESH.get(ilova) or _STANDART_BOT.get(ilova, "")
