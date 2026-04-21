import os
import json
import logging
import aiohttp
import hashlib

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ============================================================
# 1. AliExpress/1688 uchun kartochka (avvalgi funksiya)
# ============================================================
async def make_card(product_data: dict) -> str:
    if not GEMINI_API_KEY:
        return format_simple_card(product_data)

    prompt = f"""Sen XazDent dental marketplace uchun mahsulot kartochkasi yozuvchisan.

Quyidagi xom ma'lumotdan o'zbekcha professional kartochka yasa.
Javobni FAQAT JSON formatda ber, boshqa hech narsa yozma:

{{
  "name_uz": "O'zbekcha qisqa nom (20-50 belgi)",
  "description_uz": "3-5 jumlali professional tavsif stomatologlar uchun",
  "category_hint": "Kategoriya nomi"
}}

XOM MA'LUMOT:
{json.dumps(product_data, ensure_ascii=False)}"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        ai = json.loads(text)
        return format_full_card(product_data, ai)

    except Exception as e:
        logger.error(f"Gemini xatolik: {e}")
        return format_simple_card(product_data)


# ============================================================
# 2. Telegram kanal posti uchun kartochka — YANGI
# ============================================================
async def make_card_from_post(post_data: dict) -> dict | None:
    """
    Telegram kanal postidan mahsulot ma'lumotlarini ajratib oladi.
    post_data = {"text": "...", "photo_file_ids": ["file_id_1", ...]}
    """
    post_text = post_data.get("text", "").strip()
    photo_file_ids = post_data.get("photo_file_ids", [])

    if not post_text and not photo_file_ids:
        return None

    if not GEMINI_API_KEY:
        # AI siz — matndan minimal ma'lumot
        return _parse_post_simple(post_text, photo_file_ids)

    prompt = f"""Sen dental marketplace uchun ishlaydigan AI assistantsan.

Quyidagi Telegram kanal postidan mahsulot ma'lumotlarini ajrat.
Javobni FAQAT JSON formatda ber:

{{
  "name_uz": "Mahsulot nomi o'zbekcha (20-60 belgi)",
  "description_uz": "3-5 jumlali tavsif stomatologlar uchun",
  "category_hint": "Kategoriya (Stomatologik asboblar / Implant materiallari / Dezinfeksiya / Rentgen / Boshqa)",
  "price_uzs": 0
}}

Agar narx matndа bo'lsa — price_uzs ga yoz (faqat raqam, so'mda).
Agar narx yo'q bo'lsa — 0 qoldir.
Agar matn o'zbekcha/ruscha bo'lsa — o'zbekchaga tarjima qil.

KANAL POSTI MATNI:
{post_text or "(Matn yo'q, faqat rasm)"}"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        ai = json.loads(text)

        # product_id — post matnidan hash
        product_id = "post_" + hashlib.md5(post_text.encode()).hexdigest()[:8]

        price_uzs = int(ai.get("price_uzs", 0))

        product_data = {
            "product_id":   product_id,
            "title":        ai.get("name_uz", "Mahsulot"),
            "description":  ai.get("description_uz", ""),
            "category":     ai.get("category_hint", ""),
            "images":       [],                    # URL yo'q, file_id bor
            "photo_file_ids": photo_file_ids,      # Telegram file_id lar
            "price_uzs":    price_uzs,
            "price_usd":    round(price_uzs / 12800, 2),
            "price_cny":    0,
            "variants":     [],
            "min_order":    1,
            "_source":      "telegram_post",
        }

        # Kartochka matni
        product_data["card_text"] = format_post_card(product_data)

        return product_data

    except Exception as e:
        logger.error(f"make_card_from_post xatolik: {e}")
        return _parse_post_simple(post_text, photo_file_ids)


def _parse_post_simple(text: str, photo_file_ids: list) -> dict:
    """AI siz — matndan minimal ma'lumot"""
    import hashlib
    product_id = "post_" + hashlib.md5(text.encode()).hexdigest()[:8]
    return {
        "product_id":     product_id,
        "title":          text[:60] if text else "Mahsulot",
        "description":    text[:500] if text else "",
        "category":       "",
        "images":         [],
        "photo_file_ids": photo_file_ids,
        "price_uzs":      0,
        "price_usd":      0,
        "price_cny":      0,
        "variants":       [],
        "min_order":      1,
        "_source":        "telegram_post_simple",
        "card_text":      f"📦 <b>{text[:60]}</b>\n\n{text[:300]}" if text else "📦 Mahsulot",
    }


# ============================================================
# FORMAT FUNKSIYALAR
# ============================================================
def format_full_card(raw: dict, ai: dict) -> str:
    price_uzs = raw.get("price_uzs", 0)
    price_cny = raw.get("price_cny", 0)
    price_usd = raw.get("price_usd", 0)

    variants_text = ""
    for v in raw.get("variants", [])[:4]:
        values = ", ".join(v.get("values", [])[:5])
        variants_text += f"\n  • {v.get('name', '')}: {values}"

    return (
        f"✅ <b>{ai.get('name_uz', raw.get('title', 'Mahsulot'))}</b>\n"
        f"🏷 <i>{ai.get('category_hint', '')}</i>\n\n"
        f"📝 <b>Tavsif:</b>\n{ai.get('description_uz', '')}\n"
        f"{('📐 <b>Variantlar:</b>' + variants_text) if variants_text else ''}\n\n"
        f"💰 <b>Narx:</b>\n"
        f"  • 💴 {price_cny:.2f} ¥\n"
        f"  • 💵 ${price_usd:.2f}\n"
        f"  • 🇺🇿 {price_uzs:,} so'm\n\n"
        f"🔢 <b>Artikul:</b> <code>{raw.get('product_id', '—')}</code>"
    )


def format_post_card(data: dict) -> str:
    return (
        f"✅ <b>{data.get('title', 'Mahsulot')}</b>\n"
        f"🏷 <i>{data.get('category', '')}</i>\n\n"
        f"📝 <b>Tavsif:</b>\n{data.get('description', '')}\n\n"
        f"🔢 <b>ID:</b> <code>{data.get('product_id', '—')}</code>"
    )


def format_simple_card(raw: dict) -> str:
    return (
        f"📦 <b>{raw.get('title', 'Mahsulot')}</b>\n\n"
        f"📝 {raw.get('description', '')[:300]}\n\n"
        f"💰 {raw.get('price_uzs', 0):,} so'm\n"
        f"🔢 <code>{raw.get('product_id', '—')}</code>"
    )
