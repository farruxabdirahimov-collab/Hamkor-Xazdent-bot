from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
)
from app.texts import REGIONS, REGIONS_RU


def ik(*rows):
    return InlineKeyboardMarkup(inline_keyboard=list(rows))

def ib(text, data=None, url=None, web_app=None):
    if web_app:
        return InlineKeyboardButton(text=text, web_app=web_app)
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)

def rk(*rows, one_time=False):
    return ReplyKeyboardMarkup(keyboard=list(rows), resize_keyboard=True, one_time_keyboard=one_time)

def kb_lang():
    return ik([ib("🇺🇿 O'zbekcha", "lang_uz"), ib("🇷🇺 Русский", "lang_ru")])

def kb_role(lg):
    return ik(
        [ib("🏥 Vrach / Klinika",  "role_clinic")],
        [ib("🔬 Zubtexnik",         "role_zubtex")],
        [ib("🛒 Sotuvchi",          "role_seller")],
    )

def kb_clinic(lg, uid=0, webapp_url=""):
    """Klinika klaviaturasi — fokus Dental Market."""
    if webapp_url and uid:
        mkt_url = f"{webapp_url}/catalog?uid={uid}&role=clinic"
        return rk(
            [KeyboardButton(text="🛍 Dental Market — Katalog →",
                           web_app=WebAppInfo(url=mkt_url))],
            [KeyboardButton(text="📦 Buyurtmalarim"),
             KeyboardButton(text="⚙️ Profil")],
            [KeyboardButton(text="📖 Yordam")],
        )
    return rk(
        [KeyboardButton(text="🛍 Dental Market — Katalog →")],
        [KeyboardButton(text="📦 Buyurtmalarim"),
         KeyboardButton(text="⚙️ Profil")],
        [KeyboardButton(text="📖 Yordam")],
    )

def kb_seller(lg, uid=0, webapp_url=""):
    """Sotuvchi klaviaturasi — WebApp tugmalari bilan."""
    if webapp_url and uid:
        mkt_url = f"{webapp_url}/catalog?uid={uid}&role=seller"
        add_url = f"{webapp_url}/catalog?uid={uid}&role=seller&action=add"
        ord_url = f"{webapp_url}/catalog?uid={uid}&role=seller#orders"
        return rk(
            [KeyboardButton(text="🛍 Dental Market",
                           web_app=WebAppInfo(url=mkt_url))],
            [KeyboardButton(text="➕ Mahsulot qo\'shish",
                           web_app=WebAppInfo(url=add_url)),
             KeyboardButton(text="🔔 Buyurtmalar")],
            [KeyboardButton(text="💰 Hisobim"),
             KeyboardButton(text="⚙️ Profil")],
            [KeyboardButton(text="📖 Yordam")],
        )
    # Fallback — WebApp URL yo'q
    return rk(
        [KeyboardButton(text="🛍 Dental Market")],
        [KeyboardButton(text="➕ Mahsulot qo\'shish"),
         KeyboardButton(text="🔔 Buyurtmalar")],
        [KeyboardButton(text="💰 Hisobim"),
         KeyboardButton(text="⚙️ Profil")],
        [KeyboardButton(text="📖 Yordam")],
    )

def kb_regions(lg):
    regs = REGIONS if lg != "ru" else REGIONS_RU
    rows = []
    for i in range(0, len(regs), 2):
        row = [ib(regs[i], f"reg_{i}")]
        if i + 1 < len(regs):
            row.append(ib(regs[i + 1], f"reg_{i+1}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_deadline():
    return ik(
        [ib("⚡️ 2 soat", "dl_2"),  ib("🕐 24 soat", "dl_24")],
        [ib("📅 3 kun",  "dl_72"), ib("🗓 1 hafta",  "dl_168")],
    )

def kb_units():
    return ik([ib("📌 Dona", "unit_dona"), ib("⚖️ Kg", "unit_kg"), ib("💧 Litr", "unit_litr")])

def kb_delivery():
    return ik(
        [ib("⚡️ 2 soat", "del_2"),  ib("🕐 24 soat", "del_24")],
        [ib("📅 2 kun",  "del_48"), ib("🗓 1 hafta",  "del_168")],
    )

def kb_confirm():
    return ik([ib("✅ Ha, joylash", "confirm"), ib("❌ Bekor", "cancel")])

def kb_cancel():
    return ik([ib("❌ Bekor", "cancel")])

def kb_shop_cats():
    return ik(
        [ib("🦷 Terapevtik", "cat_1")],
        [ib("⚙️ Jarrohlik & Implant", "cat_2")],
        [ib("🔬 Zubtexnik", "cat_3")],
        [ib("🧪 Dezinfeksiya", "cat_4")],
        [ib("💡 Asbob-uskunalar", "cat_5")],
    )

