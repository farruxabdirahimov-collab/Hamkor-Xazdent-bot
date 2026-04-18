"""
XazDentga mahsulot yuboruvchi modul.
Bu fayl Hamkor-Xazdent-bot repo ga yangi fayl sifatida qo'shiladi.
"""

import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

# Bu 3 ta o'zgaruvchi Railway da sozlanadi
XAZDENT_API_URL = os.getenv("XAZDENT_API_URL", "")
PARTNER_TOKEN   = os.getenv("PARTNER_TOKEN", "")
SELLER_UID      = os.getenv("SELLER_UID", "")


async def upload_to_xazdent(product_data: dict) -> dict:
    """
    Mahsulotni XazDent katalogiga yuboradi.
    Muvaffaqiyatli bo'lsa: {"ok": True, "article_code": "XZ00123", "product_id": 456}
    Xatolik bo'lsa:        {"ok": False, "error": "..."}
    """

    # Sozlamalar to'liq emasmi tekshirish
    if not XAZDENT_API_URL:
        return {"ok": False, "error": "XAZDENT_API_URL sozlanmagan"}
    if not PARTNER_TOKEN:
        return {"ok": False, "error": "PARTNER_TOKEN sozlanmagan"}
    if not SELLER_UID:
        return {"ok": False, "error": "SELLER_UID sozlanmagan"}

    # Variantlarni to'g'ri formatga o'tkazish
    xazdent_variants = []
    for v in product_data.get("variants", []):
        for val in v.get("values", []):
            xazdent_variants.append({
                "size_name": f"{v.get('name', '')}: {val}",
                "article":   f"AE-{product_data.get('product_id', '')}-{val}",
                "stock":     999,
                "price":     float(product_data.get("price_uzs", 0))
            })

    # XazDentga yuboriladigan ma'lumot
    payload = {
        "uid":           int(SELLER_UID),
        "name":          product_data.get("title", "")[:200],
        "price":         float(product_data.get("price_uzs", 0)),
        "unit":          "dona",
        "description":   product_data.get("description", "")[:1000],
        "images":        product_data.get("images", [])[:5],
        "variants":      xazdent_variants[:10],
        "delivery_type": "global",
        "delivery_days": "15-30",
        "installment":   0,
        "source_url":    f"https://www.aliexpress.com/item/{product_data.get('product_id', '')}.html"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XAZDENT_API_URL}/api/partner/add_product",
                json=payload,
                headers={
                    "X-Partner-Token": PARTNER_TOKEN,
                    "Content-Type":    "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=False
            ) as resp:
                result = await resp.json()
                return result

    except Exception as e:
        logger.error(f"XazDent yuklash xatolik: {e}")
        return {"ok": False, "error": str(e)}
