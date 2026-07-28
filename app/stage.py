# -*- coding: utf-8 -*-
"""🧪 BOSQICH (stage): prod / dev — BITTA kod, TO'LIQ ALOHIDA ikkita muhit.

MAQSAD: dev — HAQIQIY sinov muhiti. O'z botlari, o'z bazasi, o'z domeni.
Sinovchi dev botга yozadi va bot UNGA JAVOB BERADI — xuddi prod kabi.
Ya'ni buyurtma berish, taklif, chat, to'lov — hammasi boshidan oxirigacha
haqiqiy tarzda sinaladi.

XAVF va uni yopish: dev bazasi — PROD nusxasi, ya'ni ichида MINGLAB HAQIQIY
foydalanuvchi id'si bor. Fon vazifalari yoki ommaviy xabar dev'да ishlaса,
dev bot HAQIQIY odamlarга yozib yuborishi mumkin edi.

Shu sabab dev'да odamlar IKKIGA bo'linadi:

  1. SINOVCHI (tester) — dev botга O'ZI yozgan odam (yoki DEV_ALLOW_IDS'да).
     Unга xabar TO'G'RIDAN, o'zgarishsiz boradi → HAQIQIY sinov.
  2. Qolgan hamma (baza nusxasidagi haqiqiy foydalanuvchilar) —
     xabar UNGA KETMAYDI. Kuzatish uchun dev guruhига «kimга ketishi kerak
     edi» sarlavhasi bilan nusxa tushadi.

Sinovchi RO'YXATDAN O'TISHI shart emas: dev botга /start yozса — avtomatik
sinovchi bo'ladi (bu ongli harakat, ya'ni rozilik).

Prod'да bu modulning HECH BIR qismi ishlamaydi — kod bir xil qoladi.

Env:
  APP_STAGE=dev              — dev rejimi (standart: prod)
  DEV_CHAT_ID=-100…          — kuzatuv guruhi (sinovchi bo'lmaganlar nusxasi)
  DEV_ALLOW_IDS=111,222      — doimiy sinovchilar (bot bilan gaplashmasa ham)
  DEV_LABEL="XAZDENT DEV"    — kuzatuv nusxasidagi yorliq
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


# ── SINOVCHILAR (testers) ────────────────────────────────────────────────────
# Dev botга o'zi yozgan har bir odam — sinovchi. Ular xabarni TO'G'RIDAN oladi,
# ya'ni dev muhit ular uchun prod'дан farq qilmaydi (haqiqiy sinov).
_TESTERS = set(DEV_ALLOW_IDS)


def is_tester(chat_id) -> bool:
    cid = _int(chat_id)
    return cid is not None and cid in _TESTERS


async def add_tester(chat_id, name: str = "", note: str = "") -> bool:
    """Sinovchini ro'yxatga oladi (xotira + baza). Yangi bo'lsa True."""
    cid = _int(chat_id)
    if cid is None or not IS_DEV or cid in _TESTERS:
        return False
    _TESTERS.add(cid)
    try:
        from app.database import db_run
        await db_run(
            "INSERT INTO dev_testers(user_id, name, note) VALUES(?,?,?) "
            "ON CONFLICT (user_id) DO NOTHING", (cid, (name or "")[:100], (note or "")[:200]))
    except Exception as e:
        log.warning("dev sinovchi saqlanmadi: %s", e)
    log.warning("🧪 DEV: yangi sinovchi %s (%s) — endi xabarlar unga to'g'ridan boradi",
                cid, name or "—")
    return True


async def load_testers():
    """Ishga tushishда bazadan sinovchilarни o'qiymiz."""
    if not IS_DEV:
        return 0
    try:
        from app.database import db_all
        rows = await db_all("SELECT user_id FROM dev_testers", ())
        for r in (rows or []):
            v = _int(r.get("user_id"))
            if v:
                _TESTERS.add(v)
    except Exception as e:
        log.warning("dev sinovchilar o'qilmadi: %s", e)
    return len(_TESTERS)


def testers() -> list:
    return sorted(_TESTERS)


def redirect(chat_id):
    """(yangi_chat_id, kuzatuv_nusxasimi). Prod'да hech narsa o'zgarmaydi.

    Dev'да:
      • sinovchi        → TO'G'RIDAN, o'zgarishsiz (haqiqiy sinov)
      • boshqa har kim  → unга KETMAYDI; dev guruhига kuzatuv nusxasi
    """
    if not IS_DEV:
        STATS["direct"] += 1
        return chat_id, False
    cid = _int(chat_id)
    if cid is not None and cid in _TESTERS:
        STATS["direct"] += 1
        return chat_id, False          # 🧪 SINOVCHI — prod kabi ishlaydi
    if cid is not None and cid < 0:
        # Guruh: dev guruhining o'zi bo'lsa to'g'ridan; boshqa guruh (prod
        # nusxasidagi sotuvchi guruhlari) — hech qachon emas.
        if DEV_CHAT_ID and str(chat_id).strip() == DEV_CHAT_ID:
            STATS["direct"] += 1
            return chat_id, False
    if not DEV_CHAT_ID:
        STATS["dropped"] += 1
        return None, True              # kuzatuv guruhi yo'q → YUBORMAYMIZ
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
                head = (f"🧪 {DEV_LABEL} · KUZATUV · {mname}\n"
                        f"👤 Bu xabar {who} ga ketishi kerak edi — "
                        f"u sinovchi emas, YUBORILMADI.\n────────────\n")
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


def tester_middleware():
    """aiogram outer-middleware: dev botга YOZGAN har kim — sinovchi.

    Shu tufayli sinovchi hech qanday ro'yxatdan o'tmaydi: dev botга /start
    yozadi va o'sha zahoti bot unга prod kabi javob bera boshlaydi.
    Prod'да middleware o'rnatilса ham hech narsa qilmaydi."""
    async def mw(handler, event, data):
        if IS_DEV:
            try:
                u = getattr(event, "from_user", None)
                if u is not None and not u.is_bot:
                    if not is_tester(u.id):
                        nm = " ".join(x for x in (getattr(u, "first_name", ""),
                                                  getattr(u, "last_name", "")) if x)
                        await add_tester(u.id, nm or (getattr(u, "username", "") or ""),
                                         "dev botга yozdi")
            except Exception as e:
                log.debug("tester_middleware: %s", e)
        return await handler(event, data)
    return mw


# ── Sinovchi HAQIQIY do'kon egasi bo'lishi (dev'да) ─────────────────────────
# Dev bazasidagi do'konlar HAQIQIY sotuvchilarники. Ular sinovchi emas, shu
# sabab buyurtma xabari ularга ketmaydi — natijaда sotuvchi tomonини sinab
# bo'lmaydi. Yechim: sinovchi dev'да do'konni O'Z NOMIGA oladi (FAQAT dev
# bazasида; prod tegilmaydi, kunlik sinxronizatsiyaда qayta tiklanadi).
async def list_shops(limit: int = 15):
    if not IS_DEV:
        return []
    try:
        from app.database import db_all
        return await db_all(
            "SELECT s.id, s.shop_name, s.owner_id, "
            "  (SELECT COUNT(*) FROM products p WHERE p.shop_id=s.id) AS n "
            "FROM shops s WHERE s.status='active' ORDER BY n DESC LIMIT ?", (int(limit),)) or []
    except Exception as e:
        log.warning("dev list_shops: %s", e)
        return []


async def takeover_shop(shop_id: int, tester_id: int):
    """Do'konni sinovchi nomiga o'tkazadi → buyurtma xabari UNGA keladi."""
    if not IS_DEV:
        return False, "faqat dev muhitда"
    if not is_tester(tester_id):
        return False, "avval botга /start yozing (sinovchi bo'ling)"
    try:
        from app.database import db_get, db_run
        sh = await db_get("SELECT id, shop_name, owner_id FROM shops WHERE id=?", (int(shop_id),))
        if not sh:
            return False, f"#{shop_id} do'kon topilmadi"
        await db_run("UPDATE shops SET owner_id=? WHERE id=?", (int(tester_id), int(shop_id)))
        await db_run("UPDATE catalog_orders SET seller_id=? WHERE shop_id=?",
                     (int(tester_id), int(shop_id)))
        log.warning("🧪 DEV: do'kon #%s (%s) sinovchi %s nomiga o'tkazildi",
                    shop_id, sh.get("shop_name"), tester_id)
        return True, sh.get("shop_name") or f"#{shop_id}"
    except Exception as e:
        log.error("dev takeover_shop: %s", e)
        return False, str(e)[:120]


def banner() -> dict:
    """Web ilovalar uchun holat (dev lentasi ko'rsatish uchun)."""
    return {
        "stage": APP_STAGE,
        "is_dev": IS_DEV,
        "label": DEV_LABEL if IS_DEV else "",
        "dev_chat_set": bool(DEV_CHAT_ID),
        "testers": len(_TESTERS) if IS_DEV else 0,
        "intercepted": dict(STATS),
    }
