import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "price_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    store TEXT NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    price REAL NOT NULL,
    stock_status TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if "image_url" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
    if "pinned" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    if "hidden" not in columns:
        # Hidden products are left out of the public (logged-out) view.
        conn.execute("ALTER TABLE products ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
    if "past" not in columns:
        # Past products (e.g. already bought) are kept off the dashboard and
        # only re-checked weekly by daily_scrape.py.
        conn.execute("ALTER TABLE products ADD COLUMN past INTEGER NOT NULL DEFAULT 0")
    if "purchased_at" not in columns:
        # When you bought it (YYYY-MM-DD) and, optionally, what you paid.
        # Without a price, the scraped price from that day is used instead.
        conn.execute("ALTER TABLE products ADD COLUMN purchased_at TEXT")
    if "purchase_price" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN purchase_price REAL")
    if "position" not in columns:
        # Seed the manual order from the previous newest-first order so the
        # dashboard looks the same until something is dragged.
        conn.execute("ALTER TABLE products ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        ids = [row[0] for row in conn.execute("SELECT id FROM products ORDER BY added_at DESC")]
        conn.executemany("UPDATE products SET position = ? WHERE id = ?", list(enumerate(ids)))

    history_columns = {row[1] for row in conn.execute("PRAGMA table_info(price_history)")}
    if "regular_price" not in history_columns:
        # NULL means the store didn't say what its regular price was.
        conn.execute("ALTER TABLE price_history ADD COLUMN regular_price REAL")
    conn.commit()
    conn.close()


def top_position(conn):
    """Position that puts a newly added product first in the manual order."""
    return conn.execute("SELECT COALESCE(MIN(position), 0) - 1 FROM products").fetchone()[0]


def update_product_image(conn, product_id, image_url):
    if image_url is None:
        return
    conn.execute("UPDATE products SET image_url = ? WHERE id = ?", (image_url, product_id))
    conn.commit()


def insert_price_check(conn, product_id, scraped, checked_at):
    conn.execute(
        "INSERT INTO price_history (product_id, price, regular_price, stock_status, checked_at) VALUES (?, ?, ?, ?, ?)",
        (product_id, scraped["price"], scraped.get("regular_price"), scraped["stock_status"], checked_at),
    )
    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
