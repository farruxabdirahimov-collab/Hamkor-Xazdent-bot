# Hamkor-Xazdent-bot

Bu loyiha XazDent uchun mahsulot kartochkalarini avtomatik tayyorlashga yo'naltirilgan.

## Tarkib
- `xazdent_ai.py` — AI yordamida stomatologik mahsulot kartochkasi yaratish logikasi
- `main.py` — JSON fayldan ma'lumot o'qib, kartochka chiqaradi
- `example_product.json` — test uchun namunaviy mahsulot ma'lumotlari
- `requirements.txt` — kerakli Python kutubxonalar
- `.gitignore` — Python loyihasi uchun oddiy sozlamalar

## O'rnatish

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Anthropic API kaliti

AI xizmati ishlashi uchun `ANTHROPIC_API_KEY` o'rnatilishi kerak:

```bash
export ANTHROPIC_API_KEY="your_api_key_here"
```

## Ishlatish

```bash
python main.py example_product.json
```

Agar kalit yo'q bo'lsa, loyiha oddiy kartochka formatini chiqaradi.

## Keyingi qadamlar

- AliExpress / 1688 / Pinduoduo sahifasidan ma'lumot yig'uvchi scraper qo'shish
- XazDent API bilan bog'lanish
- koʻproq maydonlar (rasm URL, minimal buyurtma, artikul, variantlar) qo'shish
