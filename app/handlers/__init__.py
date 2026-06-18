# -*- coding: utf-8 -*-
"""Sotuvchi bot handlerlari — import tartibi = ro'yxatga olish tartibi.

start eng birinchi (cmd_start + menyu), keyin qolganlari.
"""
from . import start       # noqa: F401  cmd_start, onboarding, menyu (Buyurtmalar/Yordam)
from . import seller      # noqa: F401  ehtiyojlar feed, takliflar, do'kon, statistika, mahsulotlar
from . import balance     # noqa: F401  💰 Hisobim + to'ldirish
from . import profile     # noqa: F401  ⚙️ Profil
from . import orders      # noqa: F401  buyurtma bajarish (seller-side)
from . import groups      # noqa: F401  /setgroup, claim
