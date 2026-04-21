import os
import json
import logging
import aiohttp
import hashlib
import base64

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Matn uchun model
TEXT_MODEL   = "llama-3.3-70b-versatile"
# Rasm uchun model
VISION_MODEL = "llama-3.2-11b-vision-preview"


async def _groq_text(prompt: str, max_tokens: int = 500) -> str | None:
    """Groq ga matn so'rovi"""
    if not GROQ_API_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": TEXT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq text xatolik: {e}")
        return None


async def _groq_vision(image_bytes: bytes, prompt: str, max_tokens: int = 600) -> str | None:
    """Groq ga rasm + matn so'rovi"""
    if not GROQ_API_KEY:
        return None
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": VISION_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }],
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                },
                timeout=aiohttp.ClientTimeout(total=40),
            ) as resp:
                data = await resp.json()

        if "choices" not in data:
            error = data.get("error", {}).get("message", str(data))
            logger.error(f"Groq vision xato: {error}")
            return None

        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.error(f"Groq vision xatolik: {e}")
        return None


# ============================================================
# 1. AliExpress/1688 uchun kartochka
# ============================================================
async def make_card(product_data: dict) -> str:
    if not GROQ_API_KEY:
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

    text = await _groq_text(prompt)
    if not text:
        return format_simple_card(product_data)

    try:
        text = text.replace("```json", "").replace("```", "").strip()
        ai = json.loads(text)
        return format_full_card(product_data, ai)
    except Exception as e:
        logger.error(f"make_card JSON parse xato: {e}")
        return format_simple_card(product_data)


# ============================================================
# 2. Telegram kanal posti uchun kartochka
# ============================================================
async def make_card_from_post(post_data: dict) -> dict | None:
    post_text      = post_data.get("text", "").strip()
    photo_file_ids = post_data.get("photo_file_ids", [])

    if not post_text and not photo_file_ids:
        return None

    if not GROQ_API_KEY:
        return _parse_post_simple(post_text, photo_file_ids)

    prompt = f"""Sen dental marketplace uchun ishlaydigan AI assistantsan.
Quyidagi Telegram kanal postidan mahsulot ma'lumotlarini ajrat.
Javobni FAQAT JSON formatda ber, boshqa hech narsa yozma:

{{
  "name_uz": "Mahsulot nomi o'zbekcha",
  "description_uz": "3-5 jumlali tavsif stomatologlar uchun",
  "category_hint": "Kategoriya",
  "price_uzs": 0
}}

Agar narx matndа bo'lsa price_uzs ga yoz. Yo'q bo'lsa 0 qoldir.

KANAL POSTI:
{post_text or "(Faqat rasm)"}"""

    text = await _groq_text(prompt)
    if not text:
        return _parse_post_simple(post_text, photo_file_ids)

    try:
        text = text.replace("```json", "").replace("```", "").strip()
        ai   = json.loads(text)

        product_id = "post_" + hashlib.md5((post_text or "x").encode()).hexdigest()[:8]
        price_uzs  = int(ai.get("price_uzs", 0))

        product_data = {
            "product_id":     product_id,
            "title":          ai.get("name_uz", "Mahsulot"),
            "description":    ai.get("description_uz", ""),
            "category":       ai.get("category_hint", ""),
            "images":         [],
            "photo_file_ids": photo_file_ids,
            "price_uzs":      price_uzs,
            "price_usd":      round(price_uzs / 12800, 2),
            "price_cny":      0,
            "variants":       [],
            "min_order":      1,
            "_source":        "telegram_post",
        }
        product_data["card_text"] = format_post_card(product_data)
        return product_data

    except Exception as e:
        logger.error(f"make_card_from_post xato: {e}")
        return _parse_post_simple(post_text, photo_file_ids)


# ============================================================
# 3. RASM dan kartochka — Vision AI
# ============================================================
async def make_card_from_image(image_bytes: bytes, filename: str = "photo.jpg") -> dict | None:
    if not GROQ_API_KEY:
        return None

    prompt = """Sen dental marketplace (stomatologiya mahsulotlari) uchun ishlaydigan AI assistantsan.

Bu rasmda stomatologiya mahsuloti ko'rinmoqda.
Rasmdan ma'lumot ajrat va FAQAT JSON formatda ber, boshqa hech narsa yozma:

{
  "name_uz": "Mahsulot nomi o'zbekcha",
  "brand": "Brend nomi",
  "model": "Model raqami",
  "shop_name": "Do'kon yoki kompaniya nomi (agar ko'rinsa, aks holda bo'sh)",
  "description_uz": "3-5 jumlali professional tavsif stomatologlar uchun",
  "category_hint": "Kategoriya (Nakonechniklar / Implant asboblari / Dezinfeksiya / Rentgen / Boshqa)",
  "price_uzs": 0,
  "price_currency": "noaniq",
  "has_other_shop_logo": false
}

MUHIM:
- Agar rasmda narx yozilgan bo'lsa price_uzs ga yoz
- Agar narx valyutasi noaniq bo'lsa price_currency = "noaniq"
- Agar rasmda boshqa do'kon logosi bo'lsa has_other_shop_logo = true
- Agar mahsulot stomatologiya bilan bog'liq bo'lmasa barcha maydonlarni bo'sh qoldir"""

    text = await _groq_vision(image_bytes, prompt)

    if not text:
        return None

    try:
        text = text.replace("```json", "").replace("```", "").strip()
        ai   = json.loads(text)

        if not ai.get("name_uz") and not ai.get("brand"):
            return {"_not_dental": True}

        product_id = "img_" + hashlib.md5(image_bytes[:100]).hexdigest()[:8]
        price_uzs  = int(ai.get("price_uzs", 0))

        product_data = {
            "product_id":          product_id,
            "title":               ai.get("name_uz", ""),
            "brand":               ai.get("brand", ""),
            "model":               ai.get("model", ""),
            "shop_name":           ai.get("shop_name", ""),
            "has_other_shop_logo": ai.get("has_other_shop_logo", False),
            "description":         ai.get("description_uz", ""),
            "category":            ai.get("category_hint", ""),
            "images":              [],
            "photo_file_ids":      [],
            "price_uzs":           price_uzs,
            "price_usd":           round(price_uzs / 12800, 2),
            "price_cny":           0,
            "price_currency":      ai.get("price_currency", "noaniq"),
            "variants":            [],
            "min_order":           1,
            "_source":             "image_vision",
        }
        product_data["card_text"] = format_image_card(product_data)
        return product_data

    except Exception as e:
        logger.error(f"make_card_from_image xato: {e}")
        return {"_error": str(e)}


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

def format_image_card(data: dict) -> str:
    brand     = data.get("brand", "")
    model     = data.get("model", "")
    brand_line = ""
    if brand:
        brand_line = f"\n🏭 <b>Brend:</b> {brand}"
        if model:
            brand_line += f" | <b>Model:</b> {model}"
    return (
        f"✅ <b>{data.get('title', 'Mahsulot')}</b>\n"
        f"🏷 <i>{data.get('category', '')}</i>"
        f"{brand_line}\n\n"
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

def _parse_post_simple(text: str, photo_file_ids: list) -> dict:
    product_id = "post_" + hashlib.md5((text or "x").encode()).hexdigest()[:8]
    return {
        "product_id": product_id,
        "title": text[:60] if text else "Mahsulot",
        "description": text[:500] if text else "",
        "category": "",
        "images": [],
        "photo_file_ids": photo_file_ids,
        "price_uzs": 0, "price_usd": 0, "price_cny": 0,
        "variants": [], "min_order": 1,
        "_source": "telegram_post_simple",
        "card_text": f"📦 <b>{text[:60]}</b>\n\n{text[:300]}" if text else "📦 Mahsulot",
    }
