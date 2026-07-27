# -*- coding: utf-8 -*-
"""🧪 BOSQICH (stage): prod / dev — BITTA kod, ikkita muhit.

MUAMMO: hozir test PROD serverда qilinади va xabarlar HAQIQIY foydalanuvchilarга
boradi. Kerak: prod bilan bir xil ishlaydigan dev muhit, lekin barcha chiqish
xabarlari BIZГА keladi.

YECHIM: kod BITTA. Farq faqat env'да. Dev'да chiqish kanallari BITTA joyда
(«choke point») ushlanadi:
    • Telegram  — bot obyektlarining send_*/edit_* metodlari (guard_bot)
    • SMS       — app/sms.send_sms (dev'да SMS ketmaydi, matn dev guruhига)
    • Web push  — dev'да yuborilmaydi
Shu sabab YANGI funksiya yozganда hech narsa qo'shish KERAK EMAS: prod'да
foydalanuvchiга, dev'да dev guruhига ketadi — o'z-o'zidan.

Env:
  APP_STAGE=dev              — dev rejimi (standart: prod)
  DEV_CHAT_ID=-100…          — barcha ushlangan xabarlar shu chatга ketadi
  DEV_ALLOW_IDS=111,222      — bu ID'lar xabarni TO'G'RIDAN oladi (dev jamoasi)
  DEV_LABEL="XAZDENT DEV"    — xabar boshidagi yorliq
"""
import logging
import os

log = logging.getLogger(__name__)

APP_STAGE = (os.getenv("APP_STAGE", "") or "prod").strip().lower()
if APP_STAGE in ("development", "develop", "staging", "stage", "test"):
    APP_STAGE = "dev"
IS_DEV = APP_STAGE == "dev"
IS_PROD = not IS_DEV

DEV_CHAT_ID = (os.getenv("DEV_CHAT_ID", "") or "").strip()
DEV_LABEL = (os.getenv("DEV_LABEL", "") or "XAZDENT DEV").strip()
DEV_ALLOW_IDS = set()
for _x in (os.getenv("DEV_ALLOW_IDS", "") or "").replace(" ", "").split(","):
    if _x.lstrip("-").isdigit():
        DEV_ALLOW_IDS.add(int(_x))

# Ushlangan xabarlar hisobi (diagnostika uchun)
STATS = {"redirected": 0, "dropped": 0, "direct": 0}


def label() -> str:
    return DEV_LABEL


def _int(v):
    try:
        return int(v)
    except Exception:
        return None


async def _describe(chat_id) -> str:
    """Xabar ASLIDA kimга ketishi kerak edi — shuni yozib qo'yamiz."""
    cid = _int(chat_id)
    if cid is None:
        return f"chat={chat_id}"
    if cid < 0:
        return f"guruh {cid}"
    try:
        from app.database import db_get
        u = await db_get("SELECT id, full_name, clinic_name, phone, role FROM users WHERE id=?",
                         (cid,))
        if u:
            nm = (u.get("clinic_name") or u.get("full_name") or "ism yo'q").strip()
            return f"{nm} · {u.get('role') or '—'} · {u.get('phone') or '—'} · id={cid}"
    except Exception:
        pass
    return f"id={cid}"


def redirect(chat_id):
    """(yangi_chat_id, ushlandimi). Prod'да hech narsa o'zgarmaydi."""
    if not IS_DEV:
        STATS["direct"] += 1
        return chat_id, False
    cid = _int(chat_id)
    if cid is not None and cid in DEV_ALLOW_IDS:
        STATS["direct"] += 1
        return chat_id, False          # dev jamoasi o'zi — to'g'ridan olsin
    if DEV_CHAT_ID and str(chat_id).strip() == DEV_CHAT_ID:
        STATS["direct"] += 1
        return chat_id, False          # allaqachon dev guruhi — sarlavha shart emas
    if not DEV_CHAT_ID:
        STATS["dropped"] += 1
        return None, True              # dev chat berilmagan → YUBORMAYMIZ
    STATS["redirected"] += 1
    return DEV_CHAT_ID, True


# ── Telegram bot obyektini o'rash ────────────────────────────────────────────
# Faqat CHIQISH metodlari. Prod'да funksiya umuman ishlamaydi (o'ramaydi).
_SEND_METHODS = (
    "send_message", "send_photo", "send_document", "send_video", "send_audio",
    "send_voice", "send_animation", "send_sticker", "send_media_group",
    "send_location", "send_contact", "send_invoice", "send_dice",
    "copy_message", "forward_message",
)
_EDIT_METHODS = (
    "edit_message_text", "edit_message_caption", "edit_message_reply_markup",
    "edit_message_media", "delete_message", "pin_chat_message",
)


def guard_bot(bot, name: str = "bot"):
    """Dev'да botning chiqish metodlarини ushlaydi. Prod'да — hech narsa."""
    if not IS_DEV or getattr(bot, "_xz_guarded", False):
        return bot

    def _wrap_send(orig, mname):
        async def inner(chat_id, *a, **kw):
            new_id, caught = redirect(chat_id)
            if new_id is None:
                log.info("[DEV] %s.%s YUBORILMADI (DEV_CHAT_ID yo'q) → %s",
                         name, mname, chat_id)
                return None
            if caught:
                who = await _describe(chat_id)
                head = f"🧪 {DEV_LABEL} · {mname}\n👤 ASLIDA: {who}\n────────────\n"
                # Matnli metodlarда sarlavhani matn boshiga qo'shamiz
                if mname == "send_message":
                    if a:
                        a = (head + str(a[0]),) + a[1:]
                    else:
                        kw["text"] = head + str(kw.get("text") or "")
                elif "caption" in kw and kw.get("caption") is not None:
                    kw["caption"] = head + str(kw["caption"])
                elif mname in ("send_photo", "send_document", "send_video",
                               "send_audio", "send_voice", "send_animation"):
                    kw["caption"] = head
                # Reply id boshqa chatда — olib tashlaymiz (aks holda xato)
                kw.pop("reply_to_message_id", None)
                kw.pop("message_thread_id", None)
            return await orig(new_id, *a, **kw)
        return inner

    def _wrap_edit(orig, mname):
        async def inner(*a, **kw):
            # chat_id birinchi pozitsion yoki kalit sifatida kelishi mumkin
            if "chat_id" in kw:
                new_id, _c = redirect(kw["chat_id"])
                if new_id is None:
                    return None
                kw["chat_id"] = new_id
            elif a:
                new_id, _c = redirect(a[0])
                if new_id is None:
                    return None
                a = (new_id,) + a[1:]
            return await orig(*a, **kw)
        return inner

    for m in _SEND_METHODS:
        f = getattr(bot, m, None)
        if callable(f):
            setattr(bot, m, _wrap_send(f, m))
    for m in _EDIT_METHODS:
        f = getattr(bot, m, None)
        if callable(f):
            setattr(bot, m, _wrap_edit(f, m))
    bot._xz_guarded = True
    log.warning("🧪 DEV: %s chiqish xabarlari ushlanadi → %s",
                name, DEV_CHAT_ID or "(YUBORILMAYDI)")
    return bot


# ── Baza belgisi: prod bazasini dev deb, dev bazasini prod deb ishlatmaslik ──
async def db_marker_check():
    """Dev bazasiga `stage_marker` yozib qo'yiladi (sinxronizatsiya skripti ham
    yozadi). Agar APP_STAGE bilan mos kelmasa — BALAND OVOZDA ogohlantiramiz.

    Bu eng xavfli xatoni oldini oladi: dev servisni PROD bazasiga ulab qo'yish
    (yoki teskarisi) — u holда dev'да qilingan test prod ma'lumotini buzardi."""
    try:
        from app.database import get_setting, update_setting
    except Exception:
        return None
    try:
        marker = (await get_setting("stage_marker") or "").strip().lower()
    except Exception:
        return None
    if not marker:
        try:
            await update_setting("stage_marker", APP_STAGE)
        except Exception:
            pass
        return APP_STAGE
    if marker != APP_STAGE:
        msg = (f"❗ BAZA MOS EMAS: APP_STAGE={APP_STAGE}, lekin bazada "
               f"stage_marker={marker}. Dev servis PROD bazasiga (yoki teskari) "
               f"ulangan bo'lishi mumkin — DARHOL tekshiring!")
        log.error(msg)
        try:
            from app import logger as xlog
            xlog.notify(msg, "ERROR")
        except Exception:
            pass
    return marker


def banner() -> dict:
    """Web ilovalar uchun holat (dev lentasi ko'rsatish uchun)."""
    return {
        "stage": APP_STAGE,
        "is_dev": IS_DEV,
        "label": DEV_LABEL if IS_DEV else "",
        "dev_chat_set": bool(DEV_CHAT_ID),
        "allow_ids": len(DEV_ALLOW_IDS),
        "intercepted": dict(STATS),
    }
