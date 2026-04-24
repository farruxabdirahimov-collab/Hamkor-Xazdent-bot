import os
import aiohttp
import logging
import base64

logger = logging.getLogger(__name__)

XAZDENT_API_URL = os.getenv("XAZDENT_API_URL", "")
PARTNER_TOKEN   = os.getenv("PARTNER_TOKEN", "")
SELLER_UID      = os.getenv("SELLER_UID", "")


async def download_telegram_photo(bot, file_id: str) -> bytes | None:
    """Telegram dan rasmni bytes sifatida yuklab olish"""
    try:
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        return file_bytes.read()
    except Exception as e:
        logger.error(f"Telegram rasm yuklab olish xatolik: {e}")
        return None


async def upload_to_xazdent(product_data: dict, bot=None) -> dict:
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

    # URL rasmlar (AliExpress/1688 dan)
    images = product_data.get("images", [])[:5]

    # Base64 rasmlar (Telegram file_id lardan)
    photo_base64 = []
    photo_file_ids = product_data.get("photo_file_ids", [])

    if photo_file_ids and bot:
        for file_id in photo_file_ids[:5]:
            img_bytes = await download_telegram_photo(bot, file_id)
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                photo_base64.append(b64)
                logger.info(f"Rasm base64 tayyor: {len(img_bytes)} bytes")

    # Source URL
    source = product_data.get("_source", "")
    source_url = ""
    if "aliexpress" in source or source in ["runParams", "json_ld", "meta_fallback"]:
        source_url = f"https://www.aliexpress.com/item/{product_data.get('product_id', '')}.html"
    elif "1688" in source:
        source_url = f"https://detail.1688.com/offer/{product_data.get('product_id', '')}.html"

    # uid — botga kirgan sotuvchining o'z Telegram ID si
    seller_uid = product_data.get("seller_uid") or SELLER_UID
    if not seller_uid:
        return {"ok": False, "error": "Sotuvchi ID topilmadi"}

    payload = {
        "uid":           int(seller_uid),
        "name":          product_data.get("title", "")[:200],
        "price":         float(product_data.get("price_uzs", 0)),
        "unit":          "dona",
        "description":   product_data.get("description", "")[:1000],
        "images":        images,           # URL rasmlar
        "photo_base64":  photo_base64,     # Telegram rasmlar base64
        "variants":      xazdent_variants[:10],
        "delivery_type": "global" if source in ["runParams", "json_ld", "1688_pattern"] else "local",
        "delivery_days": "15-30" if source in ["runParams", "json_ld", "1688_pattern"] else "2-3",
        "installment":   0,
        "source_url":    source_url,
        "category":      product_data.get("category", ""),
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
                timeout=aiohttp.ClientTimeout(total=60),
                ssl=False
            ) as resp:
                return await resp.json()

    except Exception as e:
        logger.error(f"XazDent yuklash xatolik: {e}")
        return {"ok": False, "error": str(e)}
