import re
import json
import logging
import asyncio
import aiohttp
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

logger = logging.getLogger(__name__)

# USD/CNY/UZS taxminiy kurslar (real loyihada CBU API dan oling)
USD_TO_UZS = 12800
CNY_TO_USD = 0.138  # 1 yuan ~ 0.138 USD

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def extract_product_id(url: str) -> str | None:
    """AliExpress URL dan product ID olish"""
    patterns = [
        r"/item/(\d+)\.html",
        r"productId=(\d+)",
        r"/(\d{10,})\.",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def clean_aliexpress_url(url: str) -> str:
    """URL ni tozalash — tracking parametrlarini olib tashlash"""
    parsed = urlparse(url)
    # Faqat kerakli query param — item ID
    product_id = extract_product_id(url)
    if product_id:
        return f"https://www.aliexpress.com/item/{product_id}.html"
    return url

def parse_price(price_str) -> float:
    """Narxni float ga aylantirish"""
    if isinstance(price_str, (int, float)):
        return float(price_str)
    if isinstance(price_str, str):
        # "$12.50" yoki "12,50" yoki "US $12.50"
        cleaned = re.sub(r"[^\d.,]", "", price_str)
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except:
            return 0.0
    return 0.0

def extract_data_from_html(html: str, product_id: str) -> dict | None:
    """HTML dan window.runParams yoki __NEXT_DATA__ ni olish"""
    
    # 1-usul: window.runParams
    match = re.search(r'window\.runParams\s*=\s*(\{.+?\});\s*(?:var|window|$)', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return parse_run_params(data, product_id)
        except:
            pass

    # 2-usul: data: {...} pattern
    match = re.search(r'"data"\s*:\s*(\{.*?"productId"\s*:\s*' + product_id + r'.*?\})\s*[,}]', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return parse_generic_data(data, product_id)
        except:
            pass

    # 3-usul: meta va og: taglar orqali minimal ma'lumot
    return extract_meta_fallback(html, product_id)

def parse_run_params(data: dict, product_id: str) -> dict | None:
    """window.runParams strukturasidan ma'lumot olish"""
    try:
        ae_data = data.get("data", {})
        
        # Nomi
        title = (
            ae_data.get("titleModule", {}).get("subject", "") or
            ae_data.get("pageModule", {}).get("title", "") or
            ""
        )

        # Narx
        price_module = ae_data.get("priceModule", {})
        price_usd = 0.0
        min_price = price_module.get("minAmount", {})
        if isinstance(min_price, dict):
            price_usd = parse_price(min_price.get("value", 0))
        elif price_module.get("formatedPrice"):
            price_usd = parse_price(price_module.get("formatedPrice", "0"))

        # Rasmlar
        image_module = ae_data.get("imageModule", {})
        images = image_module.get("imagePathList", [])
        images = ["https:" + img if img.startswith("//") else img for img in images]

        # Tavsif
        description_module = ae_data.get("descriptionModule", {})
        description = description_module.get("description", "")

        # Variantlar (SKU)
        sku_module = ae_data.get("skuModule", {})
        variants = []
        for prop in sku_module.get("productSKUPropertyList", []):
            prop_name = prop.get("skuPropertyName", "")
            values = [v.get("propertyValueDefinitionName", v.get("propertyValueDisplayName", ""))
                      for v in prop.get("skuPropertyValues", [])]
            if values:
                variants.append({"name": prop_name, "values": values})

        # Minimal buyurtma
        quantity_module = ae_data.get("quantityModule", {})
        min_order = quantity_module.get("minQuantity", 1)

        return {
            "product_id": product_id,
            "title": title,
            "description": description[:2000],
            "images": images[:10],
            "price_usd": price_usd,
            "price_cny": price_usd / CNY_TO_USD if price_usd else 0,
            "price_uzs": int(price_usd * USD_TO_UZS),
            "variants": variants,
            "min_order": min_order,
        }
    except Exception as e:
        logger.error(f"parse_run_params error: {e}")
        return None

def parse_generic_data(data: dict, product_id: str) -> dict | None:
    """Generic JSON strukturadan ma'lumot olish"""
    title = data.get("title", data.get("subject", ""))
    price_usd = parse_price(data.get("price", data.get("salePrice", "0")))
    images = data.get("imageList", data.get("images", []))

    return {
        "product_id": product_id,
        "title": title,
        "description": data.get("description", "")[:2000],
        "images": images[:10],
        "price_usd": price_usd,
        "price_cny": price_usd / CNY_TO_USD if price_usd else 0,
        "price_uzs": int(price_usd * USD_TO_UZS),
        "variants": [],
        "min_order": 1,
    }

def extract_meta_fallback(html: str, product_id: str) -> dict:
    """Minimal ma'lumot — og: meta taglardan"""
    title_match = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    desc_match = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
    img_match = re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', html)

    title = title_match.group(1) if title_match else f"Mahsulot #{product_id}"
    desc = desc_match.group(1) if desc_match else ""
    images = img_match[:8]
    price_usd = parse_price(price_match.group(1)) if price_match else 0.0

    return {
        "product_id": product_id,
        "title": title,
        "description": desc,
        "images": images,
        "price_usd": price_usd,
        "price_cny": price_usd / CNY_TO_USD if price_usd else 0,
        "price_uzs": int(price_usd * USD_TO_UZS),
        "variants": [],
        "min_order": 1,
        "_source": "meta_fallback",
    }

async def scrape_aliexpress(url: str) -> dict | None:
    """Asosiy scraping funksiyasi"""
    clean_url = clean_aliexpress_url(url)
    product_id = extract_product_id(clean_url) or extract_product_id(url)

    if not product_id:
        logger.error(f"Product ID topilmadi: {url}")
        return None

    logger.info(f"Scraping: {clean_url} (ID: {product_id})")

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                clean_url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
                ssl=False
            ) as resp:
                if resp.status != 200:
                    logger.error(f"HTTP {resp.status} for {clean_url}")
                    return None

                html = await resp.text(encoding="utf-8", errors="ignore")

        result = extract_data_from_html(html, product_id)

        if result:
            logger.info(f"Muvaffaqiyatli: {result.get('title', '')[:50]}")
        else:
            logger.warning(f"Ma'lumot topilmadi: {product_id}")

        return result

    except asyncio.TimeoutError:
        logger.error("Timeout — AliExpress javob bermadi")
        return None
    except Exception as e:
        logger.error(f"Scraping xatolik: {e}")
        return None
