import os
import random
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "")
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool

class Row(dict):
    pass

def _row(r):
    return Row(dict(r)) if r else None

def _rows(rs):
    return [Row(dict(r)) for r in rs]

def _q(query):
    out, n, i = [], 0, 0
    while i < len(query):
        if query[i] == '?':
            n += 1
            out.append(f"${n}")
        else:
            out.append(query[i])
        i += 1
    q = "".join(out)
    q = q.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    q = q.replace("INSERT OR REPLACE INTO", "INSERT INTO")
    q = q.replace("datetime('now')", "to_char(now(),'YYYY-MM-DD HH24:MI:SS')")
    return q

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as c:
        # users
        await c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY, username TEXT, full_name TEXT, phone TEXT,
            role TEXT DEFAULT 'none', lang TEXT DEFAULT 'uz', clinic_name TEXT,
            region TEXT, address TEXT, latitude REAL, longitude REAL,
            balance REAL DEFAULT 0, is_blocked INTEGER DEFAULT 0,
            payment_methods TEXT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        await c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS payment_methods TEXT")

        # settings
        await c.execute("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")

        # rooms
        await c.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id SERIAL PRIMARY KEY, room_code TEXT UNIQUE NOT NULL,
            room_type TEXT NOT NULL, owner_id BIGINT, status TEXT DEFAULT 'active',
            max_needs INTEGER NOT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # batches
        await c.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id SERIAL PRIMARY KEY, owner_id BIGINT NOT NULL,
            status TEXT DEFAULT 'active', deadline_hours INTEGER DEFAULT 24,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            expires_at TEXT
        )""")

        # needs
        await c.execute("""
        CREATE TABLE IF NOT EXISTS needs (
            id SERIAL PRIMARY KEY, batch_id INTEGER, room_id INTEGER,
            owner_id BIGINT, product_name TEXT NOT NULL, quantity REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT 'dona', budget REAL,
            deadline_hours INTEGER NOT NULL DEFAULT 24, extra_note TEXT,
            status TEXT DEFAULT 'active', channel_message_id BIGINT,
            payment_methods TEXT DEFAULT NULL,
            photo_file_id TEXT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            expires_at TEXT
        )""")
        await c.execute("ALTER TABLE needs ADD COLUMN IF NOT EXISTS payment_methods TEXT")
        await c.execute("ALTER TABLE needs ADD COLUMN IF NOT EXISTS photo_file_id TEXT")

        # offers
        await c.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id SERIAL PRIMARY KEY, need_id INTEGER, batch_id INTEGER,
            seller_id BIGINT, product_name TEXT NOT NULL, price REAL NOT NULL,
            unit TEXT DEFAULT 'dona', delivery_hours INTEGER NOT NULL,
            note TEXT, status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # shops
        await c.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id SERIAL PRIMARY KEY, owner_id BIGINT, shop_name TEXT NOT NULL,
            category TEXT NOT NULL, phone TEXT, region TEXT,
            status TEXT DEFAULT 'pending', rating REAL DEFAULT 0,
            total_deals INTEGER DEFAULT 0,
            group_chat_id BIGINT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        await c.execute("ALTER TABLE shops ADD COLUMN IF NOT EXISTS group_chat_id BIGINT")

        # products — avval CREATE, keyin ALTER
        await c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY, shop_id INTEGER NOT NULL,
            name TEXT NOT NULL, price REAL NOT NULL, unit TEXT NOT NULL,
            description TEXT, is_active INTEGER DEFAULT 1,
            photo_file_id TEXT DEFAULT NULL,
            stock INTEGER DEFAULT 0,
            category_id INTEGER DEFAULT 1,
            article_code TEXT UNIQUE DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS photo_file_id TEXT")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INTEGER DEFAULT 1")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS article_code TEXT")
        # article_code unique index
        await c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_article_code
        ON products(article_code) WHERE article_code IS NOT NULL""")

        # transactions
        await c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY, user_id BIGINT, amount REAL NOT NULL,
            balls REAL NOT NULL, type TEXT NOT NULL, status TEXT DEFAULT 'pending',
            receipt_file_id TEXT, confirmed_by BIGINT, note TEXT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # clinic_products
        await c.execute("""
        CREATE TABLE IF NOT EXISTS clinic_products (
            id SERIAL PRIMARY KEY, owner_id BIGINT NOT NULL,
            name TEXT NOT NULL, unit TEXT DEFAULT 'dona',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # support_messages
        await c.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
            message TEXT NOT NULL, admin_reply TEXT,
            status TEXT DEFAULT 'new', admin_id BIGINT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            replied_at TEXT
        )""")
        await c.execute("ALTER TABLE support_messages ADD COLUMN IF NOT EXISTS admin_id BIGINT")

        # product_variants — razmer, artikul, miqdor
        await c.execute("""
        CREATE TABLE IF NOT EXISTS product_variants (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            size_name TEXT,
            article TEXT,
            stock INTEGER DEFAULT 0,
            price REAL DEFAULT 0,
            extra_price REAL DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),\'YYYY-MM-DD HH24:MI:SS\')
        )""")
        await c.execute("ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS price REAL DEFAULT 0")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_type TEXT DEFAULT 'local'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_days TEXT DEFAULT '2-3'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS installment INTEGER DEFAULT 0")

        # product_photos — bir mahsulot uchun ko'p rasm
        await c.execute("""
        CREATE TABLE IF NOT EXISTS product_photos (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),\'YYYY-MM-DD HH24:MI:SS\')
        )""")

        # product_views — ko'rishlar soni
        await c.execute("""
        CREATE TABLE IF NOT EXISTS product_views (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            user_id BIGINT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # complaints — shikoyatlar
        await c.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id SERIAL PRIMARY KEY,
            from_user_id BIGINT NOT NULL,
            against_user_id BIGINT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            admin_note TEXT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # subscriptions — obuna
        await c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            status TEXT DEFAULT 'trial',
            trial_ends_at TEXT,
            paid_until TEXT,
            amount REAL DEFAULT 300000,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # search_logs — qidiruvlar
        await c.execute("""
        CREATE TABLE IF NOT EXISTS search_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            query TEXT NOT NULL,
            results_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # cart_adds — savatga qo'shishlar
        await c.execute("""
        CREATE TABLE IF NOT EXISTS cart_adds (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            product_id INTEGER,
            category_id INTEGER DEFAULT 1,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # category_clicks — kategoriya kliklari
        await c.execute("""
        CREATE TABLE IF NOT EXISTS category_clicks (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            category_id INTEGER NOT NULL,
            category_name TEXT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # catalog_orders — savat buyurtmalari tracking
        await c.execute("""
        CREATE TABLE IF NOT EXISTS catalog_orders (
            id SERIAL PRIMARY KEY,
            buyer_id BIGINT NOT NULL,
            seller_id BIGINT NOT NULL,
            products_json TEXT NOT NULL,
            total_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            confirmed_at TEXT,
            delivered_at TEXT,
            notify_sent INTEGER DEFAULT 0,
            claimed_by BIGINT DEFAULT NULL,
            group_message_id BIGINT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS claimed_by BIGINT")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS group_message_id BIGINT")
        # Mahsulot yetkazish va muddatli to'lov
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_type TEXT DEFAULT 'local'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_days TEXT DEFAULT '2-3'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS installment INTEGER DEFAULT 0")
        await c.execute("ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS price REAL DEFAULT 0")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS article_code TEXT")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS source_url TEXT")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS old_price REAL DEFAULT 0")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS discount_pct INTEGER DEFAULT 0")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_until TEXT DEFAULT NULL")

        # Bannerlar jadvali
        await c.execute("""
        CREATE TABLE IF NOT EXISTS banners (
            id SERIAL PRIMARY KEY,
            title TEXT,
            image_url TEXT DEFAULT NULL,
            file_id TEXT DEFAULT NULL,
            link_url TEXT DEFAULT '',
            banner_type TEXT DEFAULT 'main',
            status TEXT DEFAULT 'active',
            sort_order INTEGER DEFAULT 0,
            starts_at TEXT DEFAULT NULL,
            expires_at TEXT DEFAULT NULL,
            created_by BIGINT,
            xaz_cost INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        await c.execute("ALTER TABLE banners ADD COLUMN IF NOT EXISTS file_id TEXT DEFAULT NULL")
        await c.execute("ALTER TABLE banners ADD COLUMN IF NOT EXISTS starts_at TEXT DEFAULT NULL")
        await c.execute("ALTER TABLE banners ALTER COLUMN image_url SET DEFAULT ''")
        await c.execute("UPDATE banners SET image_url='' WHERE image_url IS NULL")

        # E'lonlar jadvali (yangiliklar uchun)
        await c.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            image_url TEXT,
            ann_type TEXT DEFAULT 'news',
            status TEXT DEFAULT 'active',
            expires_at TEXT DEFAULT NULL,
            created_by BIGINT,
            xaz_cost INTEGER DEFAULT 0,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")


        # ═══════════════════════════════════════════════════════════════
        # YETKAZISH VA TO'LOV TIZIMI — Hafta 1
        # ═══════════════════════════════════════════════════════════════

        # orders — asosiy buyurtma jadvali (TZ bo'yicha)
        await c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_number VARCHAR(20) UNIQUE NOT NULL,
            buyer_id BIGINT NOT NULL,
            seller_id BIGINT NOT NULL,

            -- Moliyaviy
            subtotal REAL NOT NULL DEFAULT 0,
            delivery_fee REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,

            -- To'lov
            payment_method TEXT NOT NULL DEFAULT 'cod',
            payment_status TEXT DEFAULT 'pending',
            payment_id TEXT DEFAULT NULL,
            paid_at TEXT DEFAULT NULL,

            -- Yetkazib berish
            delivery_method TEXT DEFAULT 'seller_self',
            delivery_address TEXT NOT NULL DEFAULT '',
            delivery_phone TEXT NOT NULL DEFAULT '',
            delivery_recipient_name TEXT NOT NULL DEFAULT '',
            delivery_region TEXT DEFAULT NULL,
            delivery_district TEXT DEFAULT NULL,
            delivery_notes TEXT DEFAULT NULL,
            delivery_fee_set_by TEXT DEFAULT 'seller',

            -- Status
            status TEXT DEFAULT 'pending_payment',

            -- Vaqtlar
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            accepted_at TEXT DEFAULT NULL,
            shipped_at TEXT DEFAULT NULL,
            delivered_at TEXT DEFAULT NULL,
            completed_at TEXT DEFAULT NULL,
            cancelled_at TEXT DEFAULT NULL,

            -- Qo'shimcha
            cancellation_reason TEXT DEFAULT NULL,
            buyer_notes TEXT DEFAULT NULL,
            seller_notes TEXT DEFAULT NULL,

            -- Catalog order bilan bog'lanish
            catalog_order_id INTEGER DEFAULT NULL
        )""")

        await c.execute("CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC)")

        # order_items — buyurtma mahsulotlari (snapshot)
        await c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL,

            product_name TEXT NOT NULL,
            product_price REAL NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            variant_name TEXT DEFAULT NULL,
            subtotal REAL NOT NULL,

            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        await c.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)")

        # order_deliveries — yetkazib berish tafsiloti
        await c.execute("""
        CREATE TABLE IF NOT EXISTS order_deliveries (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,

            method TEXT NOT NULL DEFAULT 'seller_self',
            estimated_date TEXT DEFAULT NULL,
            actual_delivery_date TEXT DEFAULT NULL,

            -- BTS uchun
            bts_tracking_number TEXT DEFAULT NULL,
            bts_status TEXT DEFAULT NULL,
            bts_last_updated TEXT DEFAULT NULL,

            courier_name TEXT DEFAULT NULL,
            courier_phone TEXT DEFAULT NULL,
            notes TEXT DEFAULT NULL,

            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            updated_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # order_events — audit log
        await c.execute("""
        CREATE TABLE IF NOT EXISTS order_events (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,

            event_type TEXT NOT NULL,
            actor_type TEXT DEFAULT 'system',
            actor_id BIGINT DEFAULT NULL,
            details TEXT DEFAULT NULL,

            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        await c.execute("CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id)")

        # buyer_trust_scores — xaridor ishonch darajasi
        await c.execute("""
        CREATE TABLE IF NOT EXISTS buyer_trust_scores (
            user_id BIGINT PRIMARY KEY,
            total_orders INTEGER DEFAULT 0,
            completed_orders INTEGER DEFAULT 0,
            cancelled_orders INTEGER DEFAULT 0,
            rejected_deliveries INTEGER DEFAULT 0,
            disputed_orders INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,

            trust_level TEXT DEFAULT 'new',
            cod_enabled INTEGER DEFAULT 1,
            blacklisted INTEGER DEFAULT 0,
            blacklist_reason TEXT DEFAULT NULL,

            last_order_at TEXT DEFAULT NULL,
            updated_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # seller_metrics — sotuvchi ko'rsatkichlari
        await c.execute("""
        CREATE TABLE IF NOT EXISTS seller_metrics (
            user_id BIGINT PRIMARY KEY,
            total_orders INTEGER DEFAULT 0,
            completed_orders INTEGER DEFAULT 0,
            cancelled_orders INTEGER DEFAULT 0,
            on_time_deliveries INTEGER DEFAULT 0,
            late_deliveries INTEGER DEFAULT 0,
            avg_response_time_minutes INTEGER DEFAULT NULL,
            avg_rating REAL DEFAULT NULL,
            total_reviews INTEGER DEFAULT 0,
            total_revenue REAL DEFAULT 0,
            updated_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # payment_transactions — to'lov tranzaksiyalari
        await c.execute("""
        CREATE TABLE IF NOT EXISTS payment_transactions (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            provider TEXT NOT NULL,
            provider_transaction_id TEXT DEFAULT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'created',
            raw_response TEXT DEFAULT NULL,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS'),
            updated_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # ALTER TABLE — mavjud catalog_orders ga delivery ustunlari
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS delivery_address TEXT DEFAULT NULL")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS delivery_phone TEXT DEFAULT NULL")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS delivery_recipient TEXT DEFAULT NULL")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS delivery_method TEXT DEFAULT 'seller_self'")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS delivery_fee REAL DEFAULT 0")
        await c.execute("ALTER TABLE catalog_orders ADD COLUMN IF NOT EXISTS order_ref_id INTEGER DEFAULT NULL")

        # partner_access — hamkor bot uchun ruxsat jadvali
        await c.execute("""
        CREATE TABLE IF NOT EXISTS partner_access (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            status TEXT DEFAULT 'active',
            monthly_limit INTEGER DEFAULT 50,
            used_this_month INTEGER DEFAULT 0,
            last_reset_month TEXT DEFAULT to_char(now(),'YYYY-MM'),
            granted_by BIGINT,
            note TEXT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")
        # USD kurs sozlamalari
        await c.execute("""
            INSERT INTO settings(key,value) VALUES('usd_rate','12800')
            ON CONFLICT(key) DO NOTHING
        """)
        await c.execute("""
            INSERT INTO settings(key,value) VALUES('usd_rate_updated','')
            ON CONFLICT(key) DO NOTHING
        """)
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_type TEXT DEFAULT 'local'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_days TEXT DEFAULT '2-3'")
        await c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS installment INTEGER DEFAULT 0")

        # reviews — baholar
        await c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL,
            buyer_id BIGINT NOT NULL,
            seller_id BIGINT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT DEFAULT to_char(now(),'YYYY-MM-DD HH24:MI:SS')
        )""")

        # default settings
        await c.execute("""
        INSERT INTO settings(key,value) VALUES
            ('ball_price','1000'),('elon_price','0'),('card_number','9860020138100068')
        ON CONFLICT(key) DO NOTHING""")

    print("✅ Database tayyor!")


async def db_get(query, params=()):
    pool = await get_pool()
    async with pool.acquire() as c:
        return _row(await c.fetchrow(_q(query), *params))

async def db_all(query, params=()):
    pool = await get_pool()
    async with pool.acquire() as c:
        return _rows(await c.fetch(_q(query), *params))

async def db_run(query, params=()):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute(_q(query), *params)

async def db_insert(query, params=()):
    q = _q(query)
    if "RETURNING" not in q.upper():
        q = q.rstrip(";") + " RETURNING id"
    pool = await get_pool()
    async with pool.acquire() as c:
        row = await c.fetchrow(q, *params)
        return row["id"] if row else None

async def get_user(uid):
    return await db_get("SELECT * FROM users WHERE id=?", (uid,))

async def get_setting(key):
    row = await db_get("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else None

async def update_setting(key, value):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=$2",
            key, value)

async def add_balance(user_id, balls):
    await db_run("UPDATE users SET balance=balance+? WHERE id=?", (balls, user_id))

async def get_next_room_code(room_type):
    rows = await db_all("SELECT room_code FROM rooms")
    existing = {r["room_code"] for r in rows}
    for building in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for _ in range(300):
            if room_type == "small":
                digits = random.sample(range(1,10), 3)
            elif room_type == "standard":
                d1 = random.randint(1,9)
                d2 = random.randint(1,9)
                while d2 == d1: d2 = random.randint(1,9)
                digits = random.choice([[d1,d1,d2],[d1,d2,d2]])
            else:
                d = random.randint(1,9)
                digits = [d,d,d]
            code = f"{building}-{''.join(map(str,digits))}"
            if code not in existing:
                return code
    return None


# ── ORDER YORDAMCHI FUNKSIYALAR ───────────────────────────────────────────────

async def generate_order_number():
    """XD-YYYY-NNNN formatida buyurtma raqami."""
    from datetime import datetime
    year = datetime.now().strftime("%Y")
    last = await db_get(
        "SELECT COUNT(*) as c FROM orders WHERE created_at LIKE ?",
        (f"{year}%",))
    n = (last["c"] if last else 0) + 1
    return f"XD-{year}-{n:04d}"

async def log_order_event(order_id: int, event_type: str,
                          actor_type: str = "system",
                          actor_id: int = None,
                          details: str = None):
    """Buyurtma hodisasini qayd etish."""
    await db_insert(
        "INSERT INTO order_events(order_id,event_type,actor_type,actor_id,details) "
        "VALUES(?,?,?,?,?)",
        (order_id, event_type, actor_type, actor_id, details))


# Katalog buyurtmasi hodisasi → log-guruhga (xlog). Hech qachon xato ko'tarmaydi.
_ORDER_LOG_LABELS = {
    "new": "🆕 Yangi buyurtma", "confirmed": "✅ Sotuvchi qabul qildi",
    "rejected": "❌ Sotuvchi rad etdi", "delivered": "📦 Yetkazildi",
    "partial": "⚠️ Qisman bajarildi", "disputed": "⚠️ Nizo (xaridor)",
    "completed": "🏁 Yakunlandi",
}
async def notify_order_event(order_id: int, event: str, actor_id: int = None):
    """Katalog buyurtmasi (yaratish/holat) log-guruhga tushadi. Maxfiylik: xaridor
    ism/telefoni YUBORILMAYDI — faqat raqam/summa/hudud/sotuvchi id."""
    try:
        from app import logger as _xlog
        if not _xlog._enabled():
            return
        row = await db_get(
            "SELECT co.buyer_id, co.seller_id, co.total_amount, co.order_number, "
            "co.delivery_method, u.region "
            "FROM catalog_orders co LEFT JOIN users u ON u.id=co.buyer_id WHERE co.id=?",
            (order_id,))
        if not row:
            return
        num = (row.get("order_number") or "").strip() or f"XD-{order_id}"
        total = float(row.get("total_amount") or 0)
        region = (row.get("region") or "—")
        dm = (row.get("delivery_method") or "").strip()
        lbl = _ORDER_LOG_LABELS.get(event, event)
        msg = (f"{lbl}\n🧾 {num}\n💰 {total:,.0f} so'm\n📍 {region}"
               f"\n🏪 sotuvchi #{row.get('seller_id')}")
        if dm:
            msg += f"\n🚚 {dm}"
        _xlog.notify(msg, "ORDER")
    except Exception:
        pass

async def get_or_create_trust_score(user_id: int) -> dict:
    """Xaridor trust score — yo'q bo'lsa yaratadi."""
    ts = await db_get(
        "SELECT * FROM buyer_trust_scores WHERE user_id=?", (user_id,))
    if not ts:
        await db_insert(
            "INSERT INTO buyer_trust_scores(user_id,cod_enabled) VALUES(?,1)",
            (user_id,))
        ts = await db_get(
            "SELECT * FROM buyer_trust_scores WHERE user_id=?", (user_id,))
    return ts or {}

async def update_trust_score(buyer_id: int, order_status: str):
    """Buyurtma yakunida trust score yangilash."""
    ts = await get_or_create_trust_score(buyer_id)
    completed = int(ts.get("completed_orders") or 0)
    cancelled = int(ts.get("cancelled_orders") or 0)
    rejected  = int(ts.get("rejected_deliveries") or 0)
    total     = int(ts.get("total_orders") or 0)

    if order_status == "completed":
        completed += 1; total += 1
    elif order_status == "rejected_delivery":
        rejected += 1
    elif order_status == "cancelled":
        cancelled += 1; total += 1
    else:
        total += 1

    if rejected >= 5:     level, cod = "banned", 0
    elif rejected >= 3:   level, cod = "restricted", 0
    elif completed >= 10: level, cod = "vip", 1
    elif completed >= 3:  level, cod = "trusted", 1
    elif completed >= 1:  level, cod = "verified", 1
    else:                 level, cod = "new", 1

    await db_run(
        "UPDATE buyer_trust_scores SET total_orders=?,completed_orders=?,"
        "cancelled_orders=?,rejected_deliveries=?,trust_level=?,cod_enabled=?,"
        "last_order_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS'),"
        "updated_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE user_id=?",
        (total, completed, cancelled, rejected, level, cod, buyer_id))

async def update_seller_metrics(seller_id: int, order_status: str, revenue: float = 0):
    """Sotuvchi metrikalarini yangilash."""
    sm = await db_get("SELECT * FROM seller_metrics WHERE user_id=?", (seller_id,))
    if not sm:
        await db_insert("INSERT INTO seller_metrics(user_id) VALUES(?)", (seller_id,))
        sm = await db_get("SELECT * FROM seller_metrics WHERE user_id=?", (seller_id,))
    if not sm: return
    total     = int(sm.get("total_orders") or 0)
    completed = int(sm.get("completed_orders") or 0)
    cancelled = int(sm.get("cancelled_orders") or 0)
    total_rev = float(sm.get("total_revenue") or 0)
    if order_status == "completed":
        completed += 1; total += 1; total_rev += revenue
    elif order_status == "cancelled":
        cancelled += 1; total += 1
    else:
        total += 1
    await db_run(
        "UPDATE seller_metrics SET total_orders=?,completed_orders=?,"
        "cancelled_orders=?,total_revenue=?,"
        "updated_at=to_char(now(),'YYYY-MM-DD HH24:MI:SS') WHERE user_id=?",
        (total, completed, cancelled, total_rev, seller_id))
