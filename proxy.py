# -*- coding: utf-8 -*-
"""hamkor.xazdent.uz uchun yengil reverse-proxy.

Hamkor servisi sotuvchi botni ishlatadi; bu modul shu servisda port 8080'da
web-server ham ishga tushiradi va BARCHA so'rovlarni asosiy backend
(xazdent-bot) ga uzatadi. Shunda hamkor.xazdent.uz to'liq katalogni ko'rsatadi
(brauzer location.hostname=hamkor → avtomatik SOTUVCHI rejimi), kod dublikatisiz.
"""
import os
import logging
import aiohttp
from aiohttp import web

log = logging.getLogger("app.proxy")

UPSTREAM = os.getenv("WEB_UPSTREAM", "https://xazdent-bot-production.up.railway.app").rstrip("/")

# Uzatilmaydigan (hop-by-hop / qayta hisoblanadigan) sarlavhalar
_SKIP_REQ = {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}
_SKIP_RESP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
              "content-encoding", "content-length"}


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
    app.router.add_route("*", "/{tail:.*}", _proxy)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"🌐 Hamkor web proxy: 0.0.0.0:{port} → {UPSTREAM}")
    return runner
