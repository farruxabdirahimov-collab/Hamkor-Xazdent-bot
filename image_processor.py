"""
XazDent Image Processor
Mahsulot rasmini qayta ishlaydi:
1. Fonni olib tashlaydi (rembg)
2. To'q moviy fon qo'shadi (25% blur)
3. O'ng tomonda diagonal chiziq
4. Pastki trapetsiyada XazDent logo
5. Tayyor rasm qaytaradi (bytes)
"""

import io
import os
import math
import logging
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

# === DIZAYN SOZLAMALARI ===
CANVAS_SIZE   = (1080, 1080)
BG_COLOR      = (10, 22, 40)        # To'q moviy #0A1628
STRIPE_COLOR1 = (30, 79, 191)       # Chiziq #1E4FBF
STRIPE_COLOR2 = (36, 96, 232)       # Yorqin chiziq #2460E8
TRAP_COLOR    = (27, 63, 139)       # Trapetsiya #1B3F8B
TRAP_BORDER   = (36, 96, 232)       # Trapetsiya chegara

# Logo fayl joyi — Railway da /app/xazdent_logo.png bo'lishi kerak
LOGO_PATH = os.path.join(os.path.dirname(__file__), 'xazdent_logo.png')


def remove_background(image_bytes: bytes) -> Image.Image:
    """Rasmdan fonni olib tashlaydi — rembg yoki oddiy usul"""
    try:
        from rembg import remove
        result_bytes = remove(image_bytes)
        img = Image.open(io.BytesIO(result_bytes)).convert('RGBA')
        logger.info("rembg bilan fon olib tashlandi")
        return img
    except ImportError:
        logger.warning("rembg yo'q — oddiy usul ishlatilmoqda")
        img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
        return _remove_bg_simple(img)
    except Exception as e:
        logger.error(f"rembg xatolik: {e} — oddiy usul")
        img = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
        return _remove_bg_simple(img)


def _remove_bg_simple(img: Image.Image) -> Image.Image:
    """Oddiy fon olib tashlash — oq/och ranglarni shaffof qilish"""
    data = np.array(img)
    r, g, b = data[:,:,0], data[:,:,1], data[:,:,2]
    # Oq va juda och ranglarni shaffof qilish
    mask = (r > 230) & (g > 230) & (b > 230)
    data[mask, 3] = 0
    # Qirralarni yumshatish
    result = Image.fromarray(data)
    return result


def _load_logo() -> Image.Image | None:
    """XazDent logosini yuklaydi"""
    try:
        if os.path.exists(LOGO_PATH):
            logo = Image.open(LOGO_PATH).convert('RGBA')
        else:
            # Logo yo'q bo'lsa JPEG dan yasaymiz
            jpeg_path = LOGO_PATH.replace('.png', '.jpeg')
            if os.path.exists(jpeg_path):
                logo = Image.open(jpeg_path).convert('RGBA')
                # Oq fonni olib tashlash
                data = np.array(logo)
                r, g, b = data[:,:,0], data[:,:,1], data[:,:,2]
                mask = (r > 220) & (g > 220) & (b > 220)
                data[mask, 3] = 0
                logo = Image.fromarray(data)
            else:
                logger.warning("Logo fayl topilmadi")
                return None
        return logo
    except Exception as e:
        logger.error(f"Logo yuklash xatolik: {e}")
        return None


def _make_logo_white(logo: Image.Image) -> Image.Image:
    """Logo rangini oqqa aylantirish"""
    data = np.array(logo)
    # Shaffof bo'lmagan piksellarni oq qilish
    mask = data[:,:,3] > 50
    data[mask, 0] = 255
    data[mask, 1] = 255
    data[mask, 2] = 255
    return Image.fromarray(data)


def process_product_image(
    image_bytes: bytes,
    price_uzs: int = 0,
    product_name: str = "",
) -> bytes:
    """
    Asosiy funksiya — mahsulot rasmini qayta ishlaydi.

    image_bytes — kiruvchi rasm (JPEG/PNG bytes)
    price_uzs   — narx (0 bo'lsa ko'rsatilmaydi)
    product_name — nom (ixtiyoriy)

    Qaytaradi: tayyor rasm bytes (JPEG)
    """
    W, H = CANVAS_SIZE

    # === 1. ORQA FON ===
    canvas = Image.new('RGBA', (W, H), (*BG_COLOR, 255))

    # Gradient effekti
    bg_array = np.array(canvas)
    for y in range(H):
        ratio = y / H
        bg_array[y, :, 0] = int(BG_COLOR[0] + ratio * 15)
        bg_array[y, :, 1] = int(BG_COLOR[1] + ratio * 20)
        bg_array[y, :, 2] = int(BG_COLOR[2] + ratio * 30)
    canvas = Image.fromarray(bg_array)

    # === 2. MAHSULOT RASMI ===
    try:
        product = remove_background(image_bytes)
    except Exception as e:
        logger.error(f"Fon olib tashlashda xatolik: {e}")
        product = Image.open(io.BytesIO(image_bytes)).convert('RGBA')

    # Mahsulotni markazga joylashtirish — 70% kattaroq
    max_size = int(W * 0.70)
    product.thumbnail((max_size, max_size), Image.LANCZOS)

    prod_x = (W - product.width) // 2 - 40   # Biroz chapga
    prod_y = (H - product.height) // 2 - 30  # Biroz yuqoriga

    canvas.paste(product, (prod_x, prod_y), product)

    # === 3. O'NG DIAGONAL CHIZIQLAR ===
    draw = ImageDraw.Draw(canvas)

    stripe_w1 = 90
    stripe_offset = 250

    # Birinchi (qalin) chiziq
    p1 = [
        (W - stripe_offset,           0),
        (W - stripe_offset + stripe_w1, 0),
        (W,                            H * 0.85),
        (W - stripe_w1 * 0.3,         H * 0.85),
    ]
    draw.polygon(p1, fill=(*STRIPE_COLOR1, 210))

    # Ikkinchi (ingichka, yorqin) chiziq
    stripe_w2 = 38
    p2 = [
        (W - stripe_offset + stripe_w1 + 15,  0),
        (W - stripe_offset + stripe_w1 + 15 + stripe_w2, 0),
        (W - stripe_w2 * 0.2,                  H * 0.85),
        (W,                                     H * 0.85),
    ]
    draw.polygon(p2, fill=(*STRIPE_COLOR2, 230))

    # === 4. PASTKI TRAPETSIYA — XazDent logo ===
    trap_h    = 88
    trap_y    = H - trap_h - 35
    trap_x1   = 30
    trap_x2   = 340
    skew      = 25

    trap_points = [
        (trap_x1,          trap_y),
        (trap_x2,          trap_y),
        (trap_x2 - skew,   trap_y + trap_h),
        (trap_x1,          trap_y + trap_h),
    ]
    draw.polygon(trap_points, fill=(*TRAP_COLOR, 240))
    draw.polygon(trap_points, outline=(*TRAP_BORDER, 255), width=2)

    # === 5. LOGO TRAPETSIYA ICHIDA ===
    logo = _load_logo()
    if logo:
        logo_white = _make_logo_white(logo)
        logo_target_h = 50
        logo_target_w = int(logo_white.width * logo_target_h / logo_white.height)
        logo_resized = logo_white.resize((logo_target_w, logo_target_h), Image.LANCZOS)

        # Trapetsiya markaziga joylashtirish
        trap_center_x = (trap_x1 + trap_x2) // 2
        logo_x = trap_center_x - logo_target_w // 2
        logo_y = trap_y + (trap_h - logo_target_h) // 2

        canvas.paste(logo_resized, (logo_x, logo_y), logo_resized)

    # === 6. NARX BADGE (ixtiyoriy) ===
    if price_uzs and price_uzs > 0:
        badge_x, badge_y = W - 200, 40
        badge_w, badge_h = 160, 75

        # Badge fon
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=12,
            fill=(230, 57, 70, 230)
        )

        # Narxni formatlash
        price_str = f"{price_uzs:,}".replace(",", " ")
        draw.text((badge_x + 10, badge_y + 8),  price_str, fill='white')
        draw.text((badge_x + 10, badge_y + 42), "so'm",    fill=(255, 200, 200, 255))

    # === 7. SAQLASH ===
    final = canvas.convert('RGB')
    output = io.BytesIO()
    final.save(output, format='JPEG', quality=95)
    output.seek(0)

    logger.info(f"Rasm tayyor: {len(output.getvalue())} bytes")
    return output.getvalue()


async def process_and_get_bytes(
    image_bytes: bytes,
    price_uzs: int = 0,
    product_name: str = "",
) -> bytes | None:
    """Async wrapper — bot.py dan chaqirish uchun"""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: process_product_image(image_bytes, price_uzs, product_name)
        )
        return result
    except Exception as e:
        logger.error(f"process_and_get_bytes xatolik: {e}")
        return None
