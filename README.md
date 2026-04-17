# XazDent Hamkor Bot 🦷

AliExpress mahsulot havolasini yuborish orqali tayyor dental katalog kartochkasini olish uchun Telegram bot.

## Ishlash tartibi

```
Havola yuboriladi (AliExpress)
     ↓
Scraper HTML o'qiydi
     ↓
Claude AI o'zbekcha kartochka tayyorlaydi
     ↓
Rasm + matn + xom JSON yuboriladi
```

## O'rnatish

### 1. @BotFather da yangi bot yarating
```
/newbot → nomini bering → TOKEN oling
```

### 2. Anthropic API key oling
https://console.anthropic.com → API Keys → Create Key

### 3. Railway da deploy
1. GitHub ga push qiling
2. Railway.app → New Project → GitHub Repo
3. Variables qo'shing:
   - `BOT_TOKEN` = Telegram bot tokeni
   - `ANTHROPIC_API_KEY` = Anthropic API key
4. Deploy — tayyor!

## Fayl tuzilmasi

```
├── bot.py           # Asosiy bot logikasi
├── scraper.py       # AliExpress scraper
├── ai_processor.py  # Claude AI kartochka generator
├── requirements.txt
├── railway.json     # Railway deploy config
└── .env.example     # Environment o'zgaruvchilar namunasi
```

## Eslatma

AliExpress vaqti-vaqti bilan scraping ni cheklashi mumkin.
Agar mahsulot ma'lumotlari to'liq kelmasa — havola to'g'ridan
`aliexpress.com/item/XXXXX.html` formatida yuborilganligini tekshiring.

## Kelajakdagi rivojlantirish

- [ ] XazDentga avtomatik yuklash (API integratsiya)
- [ ] 1688.com qo'shish
- [ ] Valyuta kursi CBU API dan real-time olish
- [ ] Narxga markup qo'shish (avtomatik)
- [ ] Tarixni saqlash (oxirgi N ta mahsulot)
