import re
import json
import logging
import asyncio
import aiohttp
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# =============================================================
# SOZLAMALAR
# =============================================================
SCRAPER_API_KEY = "45c389c8d08b3c2bb43dbdaa7dd2a7d3"
USD_TO_UZS = 12800
CNY_TO_USD = 0.138

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# =============================================================
# MANUAL REJIM — foydalanuvchi o'zi yozgan ma'lumot
# =============================================================
def parse_manual_input(text: str) -> dict | None:
    """
    Foydalanuvchi quyidagi formatda yozsa:
    
    mahsulot:
    nom: Dental turbina
    narx: 850000
    tavsif: Osstem implant uchun
    rasm: https://...
    
    Yoki soddaroq:
    nom: Dental turbina
    narx: 850000
    """
    text = text.strip()

    # "mahsulot:" yoki "nom:" bilan boshlanishi kerak
    if not any(text.lower().startswith(k) for k in ["mahsulot:", "nom:", "name:"]):
        return None

    result = {
        "product_id": f"manual_{abs(hash(text)) % 100000}",
        "title": "",
        "description": "",
        "images": [],
        "price_usd": 0.0,
        "price_cny": 0.0,
        "price_uzs": 0,
        "variants": [],
        "min_order": 1,
        "_source": "manual",
    }

    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key in ["nom", "name", "nomi"]:
            result["title"] = value
        elif key in ["narx", "price", "narxi"]:
            # Faqat raqamlarni olish
            digits = re.sub(r"[^\d]", "", value)
            if digits:
                price_uzs = int(digits)
                result["price_uzs"] = price_uzs
                result["price_usd"] = round(price_uzs / USD_TO_UZS, 2)
                result["price_cny"] = round(result["price_usd"] / CNY_TO_USD, 2)
        elif key in ["tavsif", "description", "tavsifi"]:
            result["description"] = value
        elif key in ["rasm", "image", "foto"]:
            if value.startswith("http"):
                result["images"].append(value)
        elif key in ["miqdor", "min_order", "minimal"]:
            digits = re.sub(r"[^\d]", "", value)
            if digits:
                result["min_order"] = int(digits)

    # Nom majburiy
    if not result["title"]:
        return None

    return result


# =============================================================
# URL YORDAMCHI FUNKSIYALAR
# =============================================================
def extract_product_id(url: str) -> str | None:
    patterns = [
        r"/item/(\d+)\.html",
        r"productId=(\d+)",
        r"/offer/(\d+)\.html",
        r"/(\d{10,})\.",
        r"id=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def clean_url(url: str) -> str:
    product_id = extract_product_id(url)
    if "1688.com" in url and product_id:
        return f"https://detail.1688.com/offer/{product_id}.html"
    if "aliexpress" in url and product_id:
        return f"https://www.aliexpress.com/item/{product_id}.html"
    return url

def parse_price(price_str) -> float:
    if isinstance(price_str, (int, float)):
        return float(price_str)
    if isinstance(price_str, str):
        cleaned = re.sub(r"[^\d.,]", "", price_str).replace(",", ".")
        try:
            return float(cleaned)
        except:
            return 0.0
    return 0.0


# =============================================================
# SCRAPERAPI ORQALI HTML OLISH
# =============================================================
async def fetch_with_scraperapi(url: str) -> str | None:
    """ScraperAPI orqali sahifani yuklash — JavaScript render bilan"""
    scraper_url = (
        f"http://api.scraperapi.com"
        f"?api_key={SCRAPER_API_KEY}"
        f"&url={url}"
        f"&render=true"          # JavaScript render
        f"&country_code=us"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                scraper_url,
                timeout=aiohttp.ClientTimeout(total=60),
                headers=HEADERS
            ) as resp:
                if resp.status == 200:
                    html = await resp.text(encoding="utf-8", errors="ignore")
                    logger.info(f"ScraperAPI muvaffaqiyatli: {len(html)} belgi")
                    return html
                else:
                    logger.error(f"ScraperAPI HTTP {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"ScraperAPI xatolik: {e}")
        return None


# =============================================================
# HTML DAN MA'LUMOT OLISH
# =============================================================
def extract_from_html(html: str, product_id: str, is_1688: bool = False) -> dict | None:
    """HTML dan mahsulot ma'lumotlarini olish"""

    # 1. JSON-LD schema
    json_ld = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for jld in json_ld:
        try:
            data = json.loads(jld.strip())
            if data.get("@type") in ["Product", "product"]:
                title = data.get("name", "")
                price_raw = 0
                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    price_raw = parse_price(offers.get("price", 0))
                elif isinstance(offers, list) and offers:
                    price_raw = parse_price(offers[0].get("price", 0))

                images = []
                img_data = data.get("image", [])
                if isinstance(img_data, str):
                    images = [img_data]
                elif isinstance(img_data, list):
                    images = img_data[:8]

                if title and price_raw:
                    price_usd = price_raw if price_raw < 1000 else price_raw / USD_TO_UZS
                    return {
                        "product_id": product_id,
                        "title": title,
                        "description": data.get("description", "")[:2000],
                        "images": images,
                        "price_usd": round(price_usd, 2),
                        "price_cny": round(price_usd / CNY_TO_USD, 2),
                        "price_uzs": int(price_usd * USD_TO_UZS),
                        "variants": [],
                        "min_order": 1,
                        "_source": "json_ld",
                    }
        except:
            pass

    # 2. window.runParams (AliExpress)
    match = re.search(r'window\.runParams\s*=\s*(\{.+?\});', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            ae = data.get("data", {})
            title = ae.get("titleModule", {}).get("subject", "")
            price_module = ae.get("priceModule", {})
            price_usd = parse_price(
                price_module.get("minAmount", {}).get("value", 0) or
                price_module.get("formatedPrice", "0")
            )
            images = ae.get("imageModule", {}).get("imagePathList", [])
            images = ["https:" + i if i.startswith("//") else i for i in images]

            variants = []
            for prop in ae.get("skuModule", {}).get("productSKUPropertyList", []):
                values = [v.get("propertyValueDisplayName", "") for v in prop.get("skuPropertyValues", [])]
                if values:
                    variants.append({"name": prop.get("skuPropertyName", ""), "values": values})

            if title:
                return {
                    "product_id": product_id,
                    "title": title,
                    "description": ae.get("descriptionModule", {}).get("description", "")[:2000],
                    "images": images[:8],
                    "price_usd": round(price_usd, 2),
                    "price_cny": round(price_usd / CNY_TO_USD, 2),
                    "price_uzs": int(price_usd * USD_TO_UZS),
                    "variants": variants,
                    "min_order": ae.get("quantityModule", {}).get("minQuantity", 1),
                    "_source": "runParams",
                }
        except:
            pass

    # 3. 1688 uchun maxsus pattern
    if is_1688:
        title_match = re.search(r'"subject"\s*:\s*"([^"]+)"', html)
        price_match = re.search(r'"priceInfo".*?"price"\s*:\s*"?([\d.]+)"?', html, re.DOTALL)
        img_matches = re.findall(r'"imageList"\s*:\s*\[([^\]]+)\]', html)

        title = title_match.group(1) if title_match else ""
        price_cny = parse_price(price_match.group(1)) if price_match else 0

        images = []
        if img_matches:
            imgs = re.findall(r'"(https?://[^"]+)"', img_matches[0])
            images = imgs[:8]

        if title:
            price_usd = price_cny * CNY_TO_USD
            return {
                "product_id": product_id,
                "title": title,
                "description": "",
                "images": images,
                "price_usd": round(price_usd, 2),
                "price_cny": round(price_cny, 2),
                "price_uzs": int(price_usd * USD_TO_UZS),
                "variants": [],
                "min_order": 1,
                "_source": "1688_pattern",
            }

    # 4. Meta fallback
    title_m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    img_m = re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    price_m = re.search(r'"price"\s*:\s*"?([\d.]+)"?', html)

    title = title_m.group(1) if title_m else f"Mahsulot #{product_id}"
    images = img_m[:5]
    price_usd = parse_price(price_m.group(1)) if price_m else 0

    return {
        "product_id": product_id,
        "title": title,
        "description": "",
        "images": images,
        "price_usd": round(price_usd, 2),
        "price_cny": round(price_usd / CNY_TO_USD, 2),
        "price_uzs": int(price_usd * USD_TO_UZS),
        "variants": [],
        "min_order": 1,
        "_source": "meta_fallback",
    }


# =============================================================
# ASOSIY SCRAPING FUNKSIYASI
# =============================================================
async def scrape_aliexpress(url: str) -> dict | None:
    """AliExpress yoki 1688 havolasidan mahsulot ma'lumotini olish"""

    is_1688 = "1688.com" in url
    clean = clean_url(url)
    product_id = extract_product_id(clean) or extract_product_id(url) or "unknown"

    logger.info(f"Scraping: {clean} (ID: {product_id})")

    # ScraperAPI bilan yuklash
    html = await fetch_with_scraperapi(clean)

    if not html:
        logger.warning("ScraperAPI ishlamadi — oddiy so'rov sinash")
        # Oddiy so'rov bilan sinab ko'rish
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(
                    clean,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                    ssl=False
                ) as resp:
                    if resp.status == 200:
                        html = await resp.text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Oddiy so'rov ham ishlamadi: {e}")
            return None

    if not html:
        return None

    result = extract_from_html(html, product_id, is_1688=is_1688)

    if result:
        source = result.get("_source", "")
        logger.info(f"Muvaffaqiyatli [{source}]: {result.get('title', '')[:50]}")
    else:
        logger.warning(f"Ma'lumot topilmadi: {product_id}")

    return result
