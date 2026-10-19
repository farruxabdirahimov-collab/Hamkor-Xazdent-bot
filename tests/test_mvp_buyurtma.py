# -*- coding: utf-8 -*-
"""MVP:H — DB/tarmoqsiz test: callback parser, karta matni, FSM oqimi."""
import asyncio
import importlib.util
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace(os.sep, "/")
sys.path.insert(0, ROOT)
os.environ["BOT_TOKEN"] = "123456:TEST_token_not_real_xxxxxxxxxxxxxxx"
os.environ.pop("DATABASE_URL", None)
os.environ["ICHKI_KALIT"] = "test"

spec = importlib.util.spec_from_file_location("mvp_buyurtma", ROOT + "/app/handlers/mvp_buyurtma.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

ok = 0


def check(c, nom):
    global ok
    assert c, nom
    ok += 1


# ── parser ──
check(M.parse_cb("mvp:qabul:12") == ("qabul", 12), "qabul")
check(M.parse_cb("mvp:yetkazildi:7") == ("yetkazildi", 7), "yetkazildi")
for yomon in ("mvp:qabul", "mvp:oldim:3", "mvp:qabul:x", "mvp:qabul:0", "mvpx:qabul:1",
              "mvp:qabul:1:2", "", None, "mvp:qabul:-5"):
    check(M.parse_cb(yomon) is None, f"yomon {yomon!r}")
check(M.parse_ichki("mvpr:5:1", "mvpr") == (5, "1"), "ichki")
check(M.parse_ichki("mvpe:5:b", "mvpe") == (5, "b"), "ichki b")
check(M.parse_ichki("mvpe:5:z", "mvpe") is None, "ichki z")
check(M.parse_ichki("mvpr:5:1", "mvpe") is None, "ichki prefiks")
check(M.tanlov_qiymat("b", M.SABABLAR) is None, "boshqa")
check(M.tanlov_qiymat("0", M.SABABLAR) == "Tugagan", "sabab0")
check(M.tanlov_qiymat("9", M.ETALAR) == "", "chegaradan tashqari")
check(M.parse_mahsulot_cb("mvpm:t:44") == ("tugadi", 44), "mahsulot t")
check(M.parse_mahsulot_cb("mvpm:x:0") == ("x", 0), "mahsulot x")
check(M.parse_mahsulot_cb("mvpm:q:1") is None, "mahsulot q")

# callback_data 64 baytdan oshmasin
big = 2 ** 62
for kb in (M.tugmalar(big, "yangi"), M.tugmalar(big, "qabul"), M.kb_sabab(big), M.kb_eta(big)):
    for row in kb.inline_keyboard:
        for b in row:
            check(len(b.callback_data.encode()) <= 64, "64 bayt")

# ── tugmalar holatga mos ──
def datalar(kb):
    return [b.callback_data for r in kb.inline_keyboard for b in r] if kb else []
check(datalar(M.tugmalar(3, "yangi")) == ["mvp:qabul:3", "mvp:rad:3"], "yangi kb")
check(datalar(M.tugmalar(3, "qabul")) == ["mvp:yolda:3", "mvp:rad:3"], "qabul kb")
check(datalar(M.tugmalar(3, "yolda")) == ["mvp:yetkazildi:3"], "yolda kb")
check(M.tugmalar(3, "yetkazildi") is None and M.tugmalar(3, "rad") is None, "yopiq kb")

# ── javob tahlili ──
check(M.yangi_holat({"ok": True, "holat": "yolda"}, "qabul") == "yolda", "holat kaliti")
check(M.yangi_holat({"ok": True, "buyurtma": {"status": "rad"}}, "rad") == "rad", "buyurtma.status")
check(M.yangi_holat({"ok": True}, "yetkazildi") == "yetkazildi", "amaldan")
check(M.xato_matn({"ok": False, "error": "Ruxsat yo'q"}) == "Ruxsat yo'q", "xato")
check(len(M.xato_matn({"error": "x" * 500})) <= 190, "xato uzunligi")
check([i["id"] for i in M.mahsulotlar_ol({"ok": True, "mahsulotlar": [{"id": 1, "nom": "A"}, {"id": "x"}, {"product_id": 2, "name": "B"}]})] == [1, 2], "mahsulotlar")
check(M.mahsulotlar_ol({"ok": True, "data": [{"id": 5, "nom": "C"}]})[0]["nom"] == "C", "data ro'yxat")

# ── karta matni + tahrir ──
row = {"id": 9, "status": "yangi", "total_amount": 150000,
       "products_json": '[{"name": "Kompozit <A2>", "qty": 2}]',
       "delivery_address": "Toshkent & Chilonzor", "delivery_phone": "+998901234567",
       "tolov_provayder": "naqd"}
k = M.karta_matn(row)
check("Kompozit &lt;A2&gt; × 2" in k and "&amp;" in k and "150 000 so'm" in k, "karta escape")
check(k.count(M.MARKER) == 1, "marker 1")
k2 = M.matn_yangila(k, "yolda", M.qoshimcha_qator("yolda", eta="Ertaga <tez>"))
check(k2.count(M.MARKER) == 1 and "🚚 Yo'lda" in k2 and "Ertaga &lt;tez&gt;" in k2 and "Yangi" not in k2, "tahrir")
k3 = M.matn_yangila("Backend matni", "qabul")
check(k3.startswith("Backend matni") and "Qabul qilindi" in k3, "backend matniga qo'shish")
check(len(M.matn_yangila("x" * 2000, "rad", "Sabab: y", limit=1024)) <= 1024, "caption limit")


# ── FSM + callback oqimi (soxta obyektlar) ──
class FakeBot:
    id = 1

    def __init__(self):
        self.edits = []

    async def edit_message_text(self, **kw):
        self.edits.append(("text", kw))

    async def edit_message_caption(self, **kw):
        self.edits.append(("caption", kw))

    async def edit_message_reply_markup(self, **kw):
        self.edits.append(("kb", kw))


class FakeMsg:
    def __init__(self, text="", html_text=None, caption=None, mid=50, bot=None, uid=777):
        self.text = text
        self.caption = caption
        self.html_text = html_text if html_text is not None else text
        self.message_id = mid
        self.chat = SimpleNamespace(id=uid, type="private")
        self.from_user = SimpleNamespace(id=uid)
        self.bot = bot
        self.answers = []
        self.kb = None

    async def answer(self, text, **kw):
        self.answers.append(text)

    async def edit_reply_markup(self, reply_markup=None):
        self.kb = reply_markup

    async def edit_text(self, text, **kw):
        self.answers.append(("edit", text))


class FakeCall:
    def __init__(self, data, message, bot, uid=777):
        self.data = data
        self.message = message
        self.bot = bot
        self.from_user = SimpleNamespace(id=uid)
        self.javoblar = []

    async def answer(self, text=None, show_alert=False):
        self.javoblar.append((text, show_alert))


chaqiruvlar = []
javob = {"ok": True}


async def fake_post(yol, tana):
    chaqiruvlar.append((yol, tana))
    return dict(javob)

M.backend_post = fake_post


async def holat_fake(oid):
    return "qabul"

M._holat_ol = holat_fake


async def main():
    global javob
    storage = MemoryStorage()
    bot = FakeBot()
    st = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=777, user_id=777))
    karta = M.karta_matn(row)

    # 1) qabul — backend chaqiriladi, karta tahrirlanadi, keyingi tugmalar
    m = FakeMsg(text="x", html_text=karta, bot=bot)
    c = FakeCall("mvp:qabul:9", m, bot)
    javob = {"ok": True, "holat": "qabul"}
    await M.cb_mvp_amal(c, st)
    yol, tana = chaqiruvlar[-1]
    check(yol == "/api/mvp/ichki/amal" and tana["order_id"] == 9 and tana["amal"] == "qabul"
          and tana["seller_tg"] == 777, "qabul tana")
    tur, kw = bot.edits[-1]
    check(tur == "text" and kw["parse_mode"] == "HTML" and "Qabul qilindi" in kw["text"], "qabul tahrir")
    check(datalar(kw["reply_markup"]) == ["mvp:yolda:9", "mvp:rad:9"], "qabul keyingi")
    check(c.javoblar[-1][1] is False, "qabul toast")

    # 2) xato — alert, tahrir yo'q
    n = len(bot.edits)
    javob = {"ok": False, "error": "Bu buyurtma sizniki emas"}
    c = FakeCall("mvp:yetkazildi:9", m, bot)
    await M.cb_mvp_amal(c, st)
    check(c.javoblar[-1] == ("Bu buyurtma sizniki emas", True) and len(bot.edits) == n, "xato alert")

    # 3) rad → sabab tugmalari (backend chaqirilmaydi)
    k0 = len(chaqiruvlar)
    c = FakeCall("mvp:rad:9", m, bot)
    await M.cb_mvp_amal(c, st)
    check(len(chaqiruvlar) == k0 and "mvpr:9:b" in datalar(m.kb), "rad sabab tugmalari")

    # 3a) tayyor sabab
    javob = {"ok": True}
    c = FakeCall("mvpr:9:1", m, bot)
    await M.cb_mvp_sabab(c, st)
    check(chaqiruvlar[-1][1]["sabab"] == "Narx o'zgargan" and chaqiruvlar[-1][1]["amal"] == "rad", "sabab tanlandi")
    check(bot.edits[-1][1]["reply_markup"] is None and "Sabab: Narx o" in bot.edits[-1][1]["text"], "rad tahrir")

    # 4) ortga
    c = FakeCall("mvpo:9", m, bot)
    await M.cb_mvp_ortga(c, st)
    check(datalar(m.kb) == ["mvp:yolda:9", "mvp:rad:9"], "ortga")

    # 5) yolda → Boshqa → FSM matn
    c = FakeCall("mvp:yolda:9", m, bot)
    await M.cb_mvp_amal(c, st)
    check("mvpe:9:b" in datalar(m.kb), "eta tugmalari")
    c = FakeCall("mvpe:9:b", m, bot)
    await M.cb_mvp_eta(c, st)
    check(await st.get_state() == M.MvpHolat.eta.state, "eta FSM holati")
    k0 = len(chaqiruvlar)
    javob = {"ok": True, "holat": "yolda"}
    t = FakeMsg(text="Juma kuni", bot=bot, mid=99)
    await M.fsm_eta(t, st)
    check(len(chaqiruvlar) == k0 + 1 and chaqiruvlar[-1][1]["eta"] == "Juma kuni"
          and chaqiruvlar[-1][1]["amal"] == "yolda", "eta yuborildi")
    tur, kw = bot.edits[-1]
    check(kw["message_id"] == 50 and "Juma kuni" in kw["text"]
          and datalar(kw["reply_markup"]) == ["mvp:yetkazildi:9"], "eta karta tahriri")
    check(await st.get_state() is None, "FSM tozalandi")

    # 6) rad → Boshqa → /bekor
    c = FakeCall("mvpr:9:b", m, bot)
    await M.cb_mvp_sabab(c, st)
    check(await st.get_state() == M.MvpHolat.rad_sabab.state, "sabab FSM")
    k0 = len(chaqiruvlar)
    t = FakeMsg(text="/bekor", bot=bot)
    await M.fsm_rad_sabab(t, st)
    check(len(chaqiruvlar) == k0 and await st.get_state() is None and t.answers, "bekor")

    # 7) FSM ichida boshqa buyruq → SkipHandler
    await M.cb_mvp_sabab(FakeCall("mvpr:9:b", m, bot), st)
    try:
        await M.fsm_rad_sabab(FakeMsg(text="/buyurtmalar", bot=bot), st)
        check(False, "skip kutilgan")
    except SkipHandler:
        check(await st.get_state() is None, "skip + tozalandi")

    # 8) caption'li karta (rasmli xabar)
    mc = FakeMsg(text=None, caption="Rasm", html_text="Rasm", bot=bot)
    javob = {"ok": True}
    await M.cb_mvp_amal(FakeCall("mvp:yetkazildi:9", mc, bot), st)
    check(bot.edits[-1][0] == "caption", "caption tahrir")

    # 9) /tugadi oqimi
    javob = {"ok": True, "mahsulotlar": [{"id": 11, "nom": "Kompozit A2", "holat": "bor"}]}
    cm = FakeMsg(text="/tugadi kompozit", bot=bot)
    cmd = SimpleNamespace(command="tugadi", args="kompozit")
    sent = {}

    async def ans(text, **kw):
        sent["t"], sent["kb"] = text, kw.get("reply_markup")
    cm.answer = ans
    await M.cmd_mahsulot_holat(cm, cmd, st)
    check(chaqiruvlar[-1][1] == {"seller_tg": 777, "qidiruv": "kompozit"}, "qidiruv tana")
    check(datalar(sent["kb"]) == ["mvpm:t:11", "mvpm:x:0"], "mahsulot tugmalari")
    pm = FakeMsg(text=sent["t"], bot=bot)
    pm.reply_markup = sent["kb"]
    javob = {"ok": True}
    c = FakeCall("mvpm:t:11", pm, bot)
    await M.cb_mahsulot_holat(c)
    check(chaqiruvlar[-1][1] == {"seller_tg": 777, "product_id": 11, "holat": "tugadi"}, "holat tana")
    check("Kompozit A2" in pm.answers[-1][1], "nom tugmadan")


asyncio.run(main())
print("OK:", ok, "tekshiruv o'tdi")
