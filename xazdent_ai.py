import os
import json
import logging
import aiohttp

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = """Sen XazDent — O'zbekistondagi stomatologik mahsulotlar platformasi uchun mahsulot kartochkalarini tayyorlaydigan AI yordamchisan.

Senga AliExpress dan olingan xom ma'lumot beriladi. Sening vazifang:
1. Mahsulot nomini o'zbek tilida aniq va professional qilib yozish
2. Stomatologik kontekstda to'g'ri tavsif yozish (dental klinikalar, stomatologlar uchun)
3. Barcha ma'lumotlarni tartibli formatlash

QOIDALAR:
- Faqat stomatologik/medical mahsulotlar bilan ishlaysan
- Nomlarni qisqa va aniq yoz (20-50 belgi)
- Tavsifni 3-5 jumlada yoz — professional, ammo tushunarli
- Artikulni saqla
- Narxlarni berilgan ko'rinishda qoldir — o'zgartirma
- Javobni FAQAT ko'rsatilgan JSON formatda qaytarish
"""


def format_simple_card(raw: dict) -> str:
    """AI bo'lmaganda oddiy kartochka formatini qaytaradi."""
    price_usd = raw.get("price_usd", 0)
    price_cny = raw.get("price_cny", 0)
    price_uzs = raw.get("price_uzs", 0)

    return (
        f"📦 <b>{raw.get('title', 'Mahsulot')}</b>\n\n"
        f"📝 {raw.get('description', '')[:300]}\n\n"
        f"💰 <b>Narx:</b>\n"
        f"  • 💴 {price_cny:.2f} ¥\n"
        f"  • 💵 ${price_usd:.2f}\n"
        f"  • 🇺🇿 {price_uzs:,} so'm\n\n"
        f"🔢 <b>Artikul:</b> <code>{raw.get('product_id', '—')}</code>\n"
        f"📦 <b>Minimal buyurtma:</b> {raw.get('min_order', 1)} dona"
    )


def format_full_card(raw: dict, ai: dict) -> str:
    """AI va xom ma'lumotlarni birlashtirib to'liq kartochka tayyorlaydi."""
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

    return (
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


async def make_card(product_data: dict) -> str:
    """Claude/Anthropic AI yordamida mahsulot kartochkasini tayyorlash."""
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY yo'q — oddiy kartochka yasalmoqda")
        return format_simple_card(product_data)

    user_prompt = f"""Quyidagi AliExpress mahsulot ma'lumotlaridan o'zbek tilidagi professional kartochka yasagaysiz.

XOM MA'LUMOT:
```json
{json.dumps(product_data, ensure_ascii=False, indent=2)}
```

Faqat quyidagi JSON formatda javob ber (boshqa hech narsa yozma):
{{
  "name_uz": "O'zbekcha professional nomi",
  "description_uz": "3-5 jumlali professional tavsif stomatologik kontekstda",
  "category_hint": "Taxminiy kategoriya (masalan: Stomatologik asboblar / Implant materiallari / Dezinfeksiya vositalari)"
}}"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 500,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        text = data["content"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        ai_result = json.loads(text)

        return format_full_card(product_data, ai_result)

    except Exception as e:
        logger.error(f"AI xatolik: {e}")
        return format_simple_card(product_data)
