# -*- coding: utf-8 -*-
"""hamkor.xazdent.uz uchun web-server (gibrid).

Hamkor servisi sotuvchi botni ishlatadi; bu modul shu servisda port 8080'da
web-server ham ishga tushiradi:

  • Sotuvchi sahifasi (catalog.html) — SHU REPODAGI webapp/ dan to'g'ridan-to'g'ri
    beriladi (brauzer location.hostname=hamkor → avtomatik SOTUVCHI rejimi).
  • Qolgan barcha so'rovlar (/api/*, rasmlar, /static, /order, ...) asosiy
    backend (xazdent-bot) ga uzatiladi — chunki ikkala bot BITTA umumiy
    Postgres bazadan foydalanadi, API kodi bitta joyda turadi (dublikatsiz).
"""
import os
import logging
import aiohttp
from aiohttp import web

log = logging.getLogger("app.proxy")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")

UPSTREAM = os.getenv("WEB_UPSTREAM", "https://xazdent-bot-production.up.railway.app").rstrip("/")

# Uzatilmaydigan (hop-by-hop / qayta hisoblanadigan) sarlavhalar
_SKIP_REQ = {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}
_SKIP_RESP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
              "content-encoding", "content-length"}

# Mahalliy beriladigan statik fayllar (sotuvchi UI)
_LOCAL_FILES = {
    "/catalog.html": "catalog.html",
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
}


def _serve_catalog():
    path = os.path.join(WEBAPP_DIR, "catalog.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html", charset="utf-8")
    return None


async def _root(request):
    """Bosh sahifa — sotuvchi katalogi (mahalliy fayl)."""
    resp = _serve_catalog()
    if resp is not None:
        return resp
    return await _proxy(request)  # zaxira: fayl yo'q bo'lsa upstream


async def _local_file(request):
    rel = _LOCAL_FILES.get(request.path)
    if rel:
        path = os.path.join(WEBAPP_DIR, rel)
        if os.path.exists(path):
            return web.FileResponse(path)
    return await _proxy(request)


async def _proxy(request):
    url = UPSTREAM + request.rel_url.raw_path_qs
    req_headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQ}
    try:
        body = await request.read()
        async with aiohttp.ClientSession(auto_decompress=True) as s:
            async with s.request(request.method, url, headers=req_headers,
                                 data=(body or None), allow_redirects=False,
                                 timeout=aiohttp.ClientTimeout(total=45)) as r:
                data = await r.read()
                resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in _SKIP_RESP}
                return web.Response(status=r.status, body=data, headers=resp_headers)
    except Exception as e:
        log.error(f"proxy xato: {e}")
        return web.Response(status=502, text="Bad gateway (hamkor proxy)")


async def start_web():
    app = web.Application(client_max_size=40 * 1024 * 1024)
    app.router.add_get("/", _root)
    for p in _LOCAL_FILES:
        app.router.add_get(p, _local_file)
    # Qolgan barcha so'rovlar — upstream backend
    app.router.add_route("*", "/{tail:.*}", _proxy)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"🌐 Hamkor web: 0.0.0.0:{port} (catalog mahalliy, /api → {UPSTREAM})")
    return runner
