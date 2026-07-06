# -*- coding: utf-8 -*-
"""AI agent uchun Groq/OpenAI-mos ekstraksiya.

Sotuvchi ixtiyoriy tilda bitta xabar yozadi (yoki rasm yuboradi) — bu modul
undan mahsulot kartochkasi maydonlarini ajratib beradi (nom, kategoriya, narx,
razmerlar, min-zakaz, bepul yetkazish, tavsif, artikul taklifi).

Kalitlar UMUMIY bazadagi `settings` jadvalidan olinadi (xaridor bot bilan bir xil):
  ai_provider (groq/grok/gemini), groq_api_key, groq_model, ...
"""
import json
import logging
import aiohttp

from app.database import get_setting

log = logging.getLogger(__name__)

# Katalog kategoriyalari (xaridor ilova bilan bir xil)
CATEGORIES = {
    1: "Terapevtik", 2: "Jarrohlik", 3: "Zubtexnik", 4: "Dezinfeksiya/Himoya",
    5: "Uskunalar", 6: "Rentgen", 7: "CAD/CAM", 8: "Implantlar",
    9: "Stom Soft", 10: "Kurslar",
}
_CAT_LIST = "\n".join(f"  {k} = {v}" for k, v in CATEGORIES.items())

# Provayder → (endpoint, default model)
_PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
    "grok": ("https://api.x.ai/v1/chat/completions", "grok-2-latest"),
}
_VISION_MODEL = {
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",  # Groq vision
    "grok": "grok-2-vision-latest",
}

_SYS = (
    "Sen XazDent — stomatologiya mahsulotlari marketpleysi uchun mahsulot kartochkasi "
    "yig'uvchi yordamchisan. Sotuvchi ixtiyoriy tilda (o'zbek/rus/ingliz) mahsulot haqida "
    "yozadi. Sen FAQAT quyidagi JSON obyektni qaytarasan (boshqa matn yo'q):\n"
    "{\n"
    '  "name": "toza, qisqa mahsulot nomi (lotin o\'zbekcha)",\n'
    '  "category_id": <1..10 son>,\n'
    '  "price": <so\'mdagi butun son, 0 agar aytilmagan>,\n'
    '  "unit": "dona|quti|to\'plam|kg|litr",\n'
    '  "sizes": ["S","M","L"...] (razmer/o\'lcham bo\'lsa, aks holda []),\n'
    '  "min_order": <minimal zakaz soni, 1 agar aytilmagan>,\n'
    '  "stock": <ombordagi soni, 0 agar aytilmagan>,\n'
    '  "free_delivery_all": <true agar butun O\'zbekiston bo\'ylab bepul yetkazish aytilgan bo\'lsa>,\n'
    '  "description": "1-2 jumlali qisqa marketing tavsifi (o\'zbekcha)",\n'
    '  "article_suggestion": "brend+turdan qisqa artikul, masalan UG-LAT-001",\n'
    '  "missing": ["price"|"images"...] (majburiy lekin yetishmayotgan maydonlar)\n'
    "}\n"
    "Kategoriya ID lari:\n" + _CAT_LIST + "\n"
    "Qo'lqop/niqob/dezinfeksiya → 4. Implant → 8. Bor/frez/asbob → 1 yoki 2. "
    "Agar 'hamma razmer' desa sizes=[\"S\",\"M\",\"L\",\"XL\"]. Narxni faqat songa aylantir "
    "(45 000 so'm → 45000). Ishonching bo'lmasa maydonni bo'sh/0 qoldir va 'missing' ga qo'sh."
)


async def _cfg():
    provider = (await get_setting("ai_provider")) or "groq"
    if provider not in _PROVIDERS:
        provider = "groq"
    keymap = {"groq": "groq_api_key", "grok": "grok_api_key"}.get(provider, "groq_api_key")
    modelmap = {"groq": "groq_model", "grok": "grok_model"}.get(provider, "groq_model")
    key = ((await get_setting(keymap)) or "").strip()
    model = ((await get_setting(modelmap)) or "").strip() or _PROVIDERS[provider][1]
    url = _PROVIDERS[provider][0]
    return provider, url, key, model


async def _chat(messages, model, url, key, want_json=True, timeout=45):
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            txt = await r.text()
            if r.status != 200:
                log.error(f"AI HTTP {r.status}: {txt[:300]}")
                return None
            try:
                data = json.loads(txt)
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                log.error(f"AI parse xato: {e} / {txt[:200]}")
                return None


def _safe_json(content):
    if not content:
        return None
    content = content.strip()
    # ba'zan ```json ... ``` bilan o'raladi
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    try:
        return json.loads(content)
    except Exception:
        # {...} qismini ajratib ko'ramiz
        i, j = content.find("{"), content.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(content[i:j + 1])
            except Exception:
                return None
    return None


async def ping():
    """AI sozlangan va ishlayaptimi? (provider, ok, xato)"""
    provider, url, key, model = await _cfg()
    if not key:
        return provider, False, "ai_not_configured"
    try:
        c = await _chat(
            [{"role": "user", "content": "javob: {\"ok\":true}"}],
            model, url, key, want_json=True, timeout=20)
        return provider, bool(c), ("" if c else "ai_error")
    except Exception as e:
        return provider, False, str(e)[:120]


def _normalize(d):
    """Model javobini xavfsiz normallaymiz."""
    if not isinstance(d, dict):
        return None
    out = {
        "name": (str(d.get("name") or "")).strip()[:200],
        "category_id": 1,
        "price": 0,
        "unit": (str(d.get("unit") or "dona")).strip()[:20] or "dona",
        "sizes": [],
        "min_order": 1,
        "stock": 0,
        "free_all": bool(d.get("free_delivery_all")),
        "description": (str(d.get("description") or "")).strip()[:2000],
        "article": (str(d.get("article_suggestion") or "")).strip()[:40],
        "missing": [],
    }
    try:
        cid = int(d.get("category_id") or 1)
        out["category_id"] = cid if cid in CATEGORIES else 1
    except Exception:
        pass
    try:
        out["price"] = max(0, round(float(d.get("price") or 0)))
    except Exception:
        pass
    try:
        out["min_order"] = max(1, int(float(d.get("min_order") or 1)))
    except Exception:
        pass
    try:
        out["stock"] = max(0, int(float(d.get("stock") or 0)))
    except Exception:
        pass
    sizes = d.get("sizes") or []
    if isinstance(sizes, list):
        out["sizes"] = [str(x).strip()[:20] for x in sizes if str(x).strip()][:20]
    miss = d.get("missing") or []
    if isinstance(miss, list):
        out["missing"] = [str(x).strip() for x in miss if str(x).strip()][:8]
    return out


async def extract_product(text):
    """Matndan mahsulot maydonlarini ajratadi. (dict|None, xato_str)"""
    provider, url, key, model = await _cfg()
    if not key:
        return None, "ai_not_configured"
    content = await _chat(
        [{"role": "system", "content": _SYS},
         {"role": "user", "content": (text or "").strip()[:3000]}],
        model, url, key, want_json=True)
    d = _safe_json(content)
    norm = _normalize(d)
    if not norm:
        return None, "ai_error"
    return norm, ""


_IMG_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


async def _cse_images(query, n, key, cx):
    """Google Custom Search (rasm) — ISHONCHLI, datacenter'dan ham ishlaydi (bepul 100/kun)."""
    import urllib.parse
    api = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
        {"key": key, "cx": cx, "q": query, "searchType": "image",
         "num": min(n, 10), "safe": "active"})
    async with aiohttp.ClientSession() as s:
        async with s.get(api, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log.error(f"CSE HTTP {r.status}: {(await r.text())[:200]}")
                return []
            data = json.loads(await r.text(errors="ignore"))
    return [it.get("link") for it in (data.get("items") or []) if (it.get("link") or "").startswith("http")][:n]


async def _ddg_images(query, n):
    """DuckDuckGo (kalitsiz) — best-effort; server IP bloklansa bo'sh qaytadi (xato rasm qo'ymaymiz)."""
    import urllib.parse
    urls = []
    try:
        async with aiohttp.ClientSession(
                headers={"User-Agent": _IMG_UA, "Accept-Language": "en-US,en;q=0.9"}) as s:
            sp = "https://duckduckgo.com/?" + urllib.parse.urlencode(
                {"q": query, "iax": "images", "ia": "images"})
            async with s.get(sp, timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text(errors="ignore")
            m = re.search(r'vqd=([\d-]+)', html) or re.search(r'vqd="([^"]+)"', html)
            if not m:
                return []
            api = "https://duckduckgo.com/i.js?" + urllib.parse.urlencode(
                {"l": "us-en", "o": "json", "q": query, "vqd": m.group(1), "f": ",,,", "p": "1"})
            async with s.get(api, headers={"Referer": sp, "Accept": "application/json, */*",
                                           "X-Requested-With": "XMLHttpRequest"},
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return []
                data = json.loads(await r.text(errors="ignore"))
            for it in (data.get("results") or []):
                u = it.get("image") or ""
                if u.startswith("http") and u.lower().rsplit("?", 1)[0].endswith(
                        (".jpg", ".jpeg", ".png", ".webp")):
                    urls.append(u)
                if len(urls) >= n:
                    break
    except Exception as e:
        log.error(f"ddg_images xato: {e}")
    return urls


async def search_images(query, n=6):
    """Rasm qidiruv. Avval Google CSE (kalit sozlangan bo'lsa — ishonchli),
    aks holda DuckDuckGo (best-effort). Natija: rasm URL ro'yxati."""
    query = (query or "").strip()
    if not query:
        return []
    # dental kontekst — relevantlikni oshiradi
    q = query if "dental" in query.lower() else (query + " dental")
    key = ((await get_setting("google_cse_key")) or "").strip()
    cx = ((await get_setting("google_cse_id")) or "").strip()
    if key and cx:
        try:
            urls = await _cse_images(q, n, key, cx)
            if urls:
                return urls
        except Exception as e:
            log.error(f"CSE xato: {e}")
    return await _ddg_images(q, n)


async def download_image_b64(url):
    """Rasmni yuklab base64 (header'siz) qaytaradi. Xato/katta bo'lsa None."""
    import base64
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _IMG_UA}) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                if r.status != 200:
                    return None
                ct = (r.headers.get("Content-Type") or "").lower()
                if "image" not in ct:
                    return None
                raw = await r.read()
        if len(raw) < 800 or len(raw) > 3_000_000:   # juda kichik/katta
            return None
        return base64.b64encode(raw).decode()
    except Exception as e:
        log.error(f"download_image_b64 xato: {e}")
        return None


async def extract_sizes_from_image(image_data_url):
    """Razmer jadvali rasmidan o'lchamlarni ajratadi. → (sizes_list, xato)."""
    provider, url, key, model = await _cfg()
    vmodel = _VISION_MODEL.get(provider)
    if not key or not vmodel:
        return [], "vision_not_available"
    msgs = [{
        "role": "user",
        "content": [
            {"type": "text", "text":
                "Bu rasmda mahsulot razmerlari/o'lchamlari bormi? "
                "FAQAT JSON qaytar: {\"sizes\":[\"S\",\"M\",...]}. Yo'q bo'lsa {\"sizes\":[]}."},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ],
    }]
    content = await _chat(msgs, vmodel, url, key, want_json=True, timeout=60)
    d = _safe_json(content) or {}
    sizes = d.get("sizes") or []
    if isinstance(sizes, list):
        return [str(x).strip()[:20] for x in sizes if str(x).strip()][:20], ""
    return [], ""
