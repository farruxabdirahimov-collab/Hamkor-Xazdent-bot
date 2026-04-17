import os
import json
import logging
import aiohttp

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

SYSTEM_PROMPT = """Sen XazDent — O'zbekistondagi stomatologik mahsulotlar platformasi uchun mahsulot kartochkalarini tayyorlaydigan AI yordamchisan.

Senga AliExpress dan olingan xom ma'lumot beriladi. Sening vazifang:
1. Mahsulot nomini o'zbek tilida aniq va professional qilib yozish
2. Stomatologik kontekstda to'g'ri tavsif yozish (dental klinikalar, stomatologlar uchun)
3. Barcha ma'lumotlarni tartibli formatlash

QOIDALAR:
- Nomlarni qisqa va aniq yoz (20-50 belgi)
- Tavsifni 3-5 jumlada yoz — professional, ammo tushunarli
- Javobni FAQAT JSON formatda qaytarish — boshqa hech narsa yozma
- JSON dan oldin va keyin hech narsa yozma"""

async def make_card(product_data: dict) -> str:
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY yo'q — oddiy kartochka yasalmoqda")
        return format_simple_card(product_data)

    user_prompt = f"""{SYSTEM_PROMPT}

Quyidagi AliExpress mahsulot ma'lumotlaridan o'zbek tilidagi professional kartochka yasa:

{json.dumps(product_data, ensure_ascii=False, indent=2)}

Faqat quyidagi JSON formatda javob ber:
{{
  "name_uz": "O'zbekcha professional nomi",
  "description_uz": "3-5 jumlali professional tavsif stomatologik kontekstda",
  "category_hint": "Taxminiy kategoriya (masalan: Stomatologik asboblar / Implant materiallari / Dezinfeksiya vositalari)"
}}"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 500,
                    }
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        ai_result = json.loads(text)
        return format_full_card(product_data, ai_result)

    except Exception as e:
        logger.error(f"Gemini xatolik: {e}")
        return format_simple_card(product_data)


def format_full_card(raw: dict, ai: dict) -> str:
    price_usd = raw.get("price_usd", 0)
    price_cny = raw.get("price_cny", 0)
    price_uzs = raw.get("price_uzs", 0)

    variants_text = ""
    if raw.get("variants"):
        lines = []
        for v in raw["variants"][:4]:
            name = v.get("name", "")
            values = ", ".join(v.get("values", [])[:6])
            lines.append(f"  • {name}: {values}")
        variants_text = "\n📐 <b>Variantlar:</b>\n" + "\n".join(lines)

    card = (
        f"✅ <b>{ai.get('name_uz', raw.get('title', 'Mahsulot'))}</b>\n"
        f"🏷 <i>{ai.get('category_hint', '')}</i>\n\n"
        f"📝 <b>Tavsif:</b>\n{ai.get('description_uz', '')}\n"
        f"{variants_text}\n\n"
        f"💰 <b>Narx:</b>\n"
        f"  • 💴 {price_cny:.2f} ¥ (Yuan)\n"
        f"  • 💵 ${price_usd:.2f} (USD)\n"
        f"  • 🇺🇿 {price_uzs:,} so'm (taxminiy)\n\n"
        f"🔢 <b>Artikul:</b> <code>{raw.get('product_id', '—')}</code>\n"
        f"📦 <b>Minimal buyurtma:</b> {raw.get('min_order', 1)} dona"
    )
    return card


def format_simple_card(raw: dict) -> str:
    price_usd = raw.get("price_usd", 0)
    price_cny = raw.get("price_cny", 0)
    price_uzs = raw.get("price_uzs", 0)

    card = (
        f"📦 <b>{raw.get('title', 'Mahsulot')}</b>\n\n"
        f"📝 {raw.get('description', '')[:300]}\n\n"
        f"💰 <b>Narx:</b>\n"
        f"  • 💴 {price_cny:.2f} ¥\n"
        f"  • 💵 ${price_usd:.2f}\n"
        f"  • 🇺🇿 {price_uzs:,} so'm\n\n"
        f"🔢 <b>Artikul:</b> <code>{raw.get('product_id', '—')}</code>\n"
        f"📦 <b>Minimal buyurtma:</b> {raw.get('min_order', 1)} dona"
    )
    return card
