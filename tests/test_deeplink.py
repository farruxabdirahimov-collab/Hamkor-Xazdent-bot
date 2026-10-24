# -*- coding: utf-8 -*-
"""DL — Hamkor bot: app/deeplink.py (nusxa) + `/start <kod>` (app/handlers/start.py, app/deeplink_bot.py).
DB/tarmoqsiz (soxta xabar). Ishga tushirish:  D:/ham_venv/Scripts/python.exe tests/test_deeplink.py"""
import asyncio
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["BOT_TOKEN"] = "123456:TEST_token_not_real_xxxxxxxxxxxxxxx"
os.environ.pop("DATABASE_URL", None)
os.environ["TG_BOT_HAMKOR"] = "hamkorXazdentbot"

from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.storage.base import StorageKey  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

from app import deeplink as dl  # noqa: E402
from app import seller_link  # noqa: E402
from app.handlers import start as S  # noqa: E402
from app.config import HAMKOR_URL  # noqa: E402

YOPILDI, MENYU, ULANGAN = [], [], {"uid": 77}


async def f_ulangan(tg):
    return ULANGAN["uid"]


async def f_yop(suid):
    YOPILDI.append(suid)
    return True


async def f_menyu(msg, suid, yopildi=False):
    MENYU.append(suid)


async def f_ulanmagan(msg):
    MENYU.append("ulanmagan")


seller_link.ulangan_sotuvchi = f_ulangan
seller_link.panel_sessiyalarini_yop = f_yop
S.sotuvchi_menyu = f_menyu
S.ulanmagan_javob = f_ulanmagan


class Msg:
    def __init__(self, text):
        self.text = text
        self.chat = SimpleNamespace(type="private", id=555)
        self.from_user = SimpleNamespace(id=555, full_name="Sotuvchi")
        self.javob = []

    async def answer(self, text, reply_markup=None, **kw):
        self.javob.append((text, reply_markup))


def _start(text):
    m = Msg(text)
    st = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=555, user_id=555))
    YOPILDI.clear(), MENYU.clear()
    asyncio.run(S.cmd_start(m, st))
    return m


def _url(m):
    return m.javob[-1][1].inline_keyboard[0][0].web_app.url


def test_modul_backend_bilan_bir_xil():
    asl = "D:/wt/dl/app/deeplink.py"
    if os.path.exists(asl):
        a = open(asl, encoding="utf-8").read().replace("\r\n", "\n")
        b = open(os.path.join(ROOT, "app", "deeplink.py"), encoding="utf-8").read().replace("\r\n", "\n")
        assert a == b, "app/deeplink.py nusxasi xazdent-backend dagidan farq qiladi"


def test_hamkor_kodlari():
    assert dl.ochish("h-ulashish", "hamkor")["yol"] == "mvp-ulashish"
    assert dl.ochish("ho5", "hamkor")["tur"] == "h_buyurtma"
    assert dl.ochish("hp6", "hamkor")["tur"] == "h_mahsulot"
    assert dl.ochish("s12", "hamkor") is None and dl.ochish("hamkorlik", "hamkor") is None
    assert dl.havolalar(dl.kodla("h", "ulashish"), "hamkor")["havola"] == "https://t.me/hamkorXazdentbot?start=h-ulashish"


def test_start_bolim_ulangan():
    ULANGAN["uid"] = 77
    m = _start("/start h-ulashish")
    assert _url(m) == HAMKOR_URL + "/?kirish=1&startapp=h-ulashish"
    assert m.javob[-1][1].inline_keyboard[0][0].text == "🏪 Kabinetni ochish"
    assert not YOPILDI and not MENYU                 # havola sessiyalarni yopmaydi, menyu yubormaydi
    assert "login" not in m.javob[-1][0]


def test_start_buyurtma_ulanmagan():
    ULANGAN["uid"] = 0
    m = _start("/start ho5__tg")
    assert _url(m) == HAMKOR_URL + "/?kirish=1&startapp=ho5__tg"
    assert "#5" in m.javob[-1][0] and "login" in m.javob[-1][0]


def test_start_parametrsiz_ozgarmadi():
    ULANGAN["uid"] = 77
    m = _start("/start")
    assert YOPILDI == [77] and MENYU == [77] and not m.javob
    ULANGAN["uid"] = 0
    _start("/start")
    assert MENYU == ["ulanmagan"] and not YOPILDI


def test_start_begona_kod():
    ULANGAN["uid"] = 77
    _start("/start s12")                                # xaridor kodi — oddiy /start
    assert YOPILDI == [77] and MENYU == [77]
    _start("/start h-yoq")
    assert YOPILDI == [77] and MENYU == [77]


if __name__ == "__main__":
    n = 0
    for nomi, fn in sorted(globals().items()):
        if nomi.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("OK", nomi)
    print(f"{n} test o'tdi")
