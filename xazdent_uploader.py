import os
import aiohttp
import logging

logger = logging.getLogger(__name__)

XAZDENT_API_URL = os.getenv("XAZDENT_API_URL", "")
PARTNER_TOKEN   = os.getenv("PARTNER_TOKEN", "")
SELLER_UID      = os.getenv("SELLER_UID", "")


async def upload_to_xazdent(product_data: dict) -> dict:
    if not XAZDENT_API_URL:
        return {"ok": False, "error": "XAZDENT_API_URL sozlanmagan"}
    if not PARTNER_TOKEN:
        return {"ok": False, "error": "PARTNER_TOKEN sozlanmagan"}
    if not SELLER_UID:
        return {"ok": False, "error": "SELLER_UID sozlanmagan"}

    # Variantlar
    xazdent_variants = []
    for v in product_data.get("variants", []):
        for val in v.get("values", []):
            xazdent_variants.append({
                "size_name": f"{v.get('name', '')}: {val}",
                "article":   f"AE-{product_data.get('product_id', '')}-{val}",
                "stock":     999,
                "price":     float(product_data.get("price_uzs", 0))
            })

    # Rasmlar — URL yoki file_id
    images = product_data.get("images", [])

    # Telegram kanal postidan kelgan bo'lsa file_id lar bor
    # Bular XazDent ga file_id sifatida yuboriladi
    photo_file_ids = product_data.get("photo_file_ids", [])

    source = product_data.get("_source", "")
    source_url = ""
    if "aliexpress" in source or source in ["runParams", "json_ld", "meta_fallback"]:
        source_url = f"https://www.aliexpress.com/item/{product_data.get('product_id', '')}.html"
    elif "1688" in source:
        source_url = f"https://detail.1688.com/offer/{product_data.get('product_id', '')}.html"

    payload = {
        "uid":            int(SELLER_UID),
        "name":           product_data.get("title", "")[:200],
        "price":          float(product_data.get("price_uzs", 0)),
        "unit":           "dona",
        "description":    product_data.get("description", "")[:1000],
        "images":         images[:5],
        "photo_file_ids": photo_file_ids[:5],   # Telegram file_id lar
        "variants":       xazdent_variants[:10],
        "delivery_type":  "global" if "1688" in source or "aliexpress" in source else "local",
        "delivery_days":  "15-30" if "global" in source else "2-3",
        "installment":    0,
        "source_url":     source_url,
        "category":       product_data.get("category", ""),
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
                return await resp.json()

    except Exception as e:
        logger.error(f"XazDent yuklash xatolik: {e}")
        return {"ok": False, "error": str(e)}
