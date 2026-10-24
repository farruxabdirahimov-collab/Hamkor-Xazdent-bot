# -*- coding: utf-8 -*-
"""🧪 DEV buyruqlari — sotuvchi tomonini HAQIQIY sinash uchun.

MUAMMO: dev bazasi prod nusxasi, ya'ni do'konlar HAQIQIY sotuvchilarники.
Ular sinovchi emas → buyurtma xabari ularга ketmaydi (to'g'ri, shunday
bo'lishi kerak). Lekin u holда sotuvchi tomonини sinab bo'lmaydi.

YECHIM: sinovchi dev'да do'konni O'Z NOMIGA oladi. Shundan keyin o'sha
do'kon mahsulotiga buyurtma berilса, xabar UNGA keladi va butun oqim
(qabul qilish → yetkazish → chat → to'lov) haqiqiy tarzda sinaladi.

Bu o'zgarish FAQAT dev bazasida. Prod tegilmaydi va kunlik sinxronizatsiya
(04:00) do'konlarни prod holatiga qaytaradi.

Prod'да barcha buyruqlar JIM — hech qanday javob bermaydi.
"""
from aiogram import Router
from aiogram.filters import Command

from app import stage as st

router = Router()

HELP = (
    "🧪 *DEV buyruqlari*\n\n"
    "/dev\\_shops — do'konlar ro'yxati\n"
    "/dev\\_take <id> — do'konni o'z nomingizga olish "
    "(buyurtma xabari SIZГА keladi)\n"
    "/dev\\_who — holatingiz\n\n"
    "_Bu o'zgarish faqat DEV bazasida. Har kuni 04:00 da prod nusxasi bilan "
    "qayta tiklanadi._"
)


@router.message(Command("dev"))
async def dev_help(m):
    if not st.IS_DEV:
        return
    await m.answer(HELP, parse_mode="Markdown")


@router.message(Command("dev_shops"))
async def dev_shops(m):
    if not st.IS_DEV:
        return
    rows = await st.list_shops(15)
    if not rows:
        await m.answer("Do'kon topilmadi.")
        return
    lines = []
    for r in rows:
        mine = " ✅ sizniki" if int(r.get("owner_id") or 0) == m.from_user.id else ""
        lines.append(f"`{r['id']}` · {r.get('shop_name') or '—'} · "
                     f"{r.get('n') or 0} mahsulot{mine}")
    await m.answer("🧪 *DEV — do'konlar*\n\n" + "\n".join(lines) +
                   "\n\nO'z nomingizga olish: `/dev_take <id>`",
                   parse_mode="Markdown")


@router.message(Command("dev_take"))
async def dev_take(m):
    if not st.IS_DEV:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("Ishlatish: `/dev_take 12`", parse_mode="Markdown")
        return
    ok, info = await st.takeover_shop(int(parts[1]), m.from_user.id)
    if ok:
        await m.answer(f"✅ «{info}» endi sizniki.\n\n"
                       f"Shu do'kon mahsulotiga buyurtma berilsa, xabar "
                       f"SIZGA keladi — butun oqimni sinab ko'rishingiz mumkin.")
    else:
        await m.answer(f"⚠️ {info}")


@router.message(Command("dev_who"))
async def dev_who(m):
    if not st.IS_DEV:
        return
    yes = "✅ ha" if st.is_tester(m.from_user.id) else "❌ yo'q"
    await m.answer(f"🧪 Muhit: *{st.APP_STAGE}*\n"
                   f"Siz sinovchisiz: {yes}\n"
                   f"ID: `{m.from_user.id}`\n"
                   f"Jami sinovchi: {len(st.testers())}",
                   parse_mode="Markdown")
