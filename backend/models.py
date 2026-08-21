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
    conn.commit()
    conn.close()


def update_product_image(conn, product_id, image_url):
    if image_url is None:
        return
    conn.execute("UPDATE products SET image_url = ? WHERE id = ?", (image_url, product_id))
    conn.commit()


def insert_price_check(conn, product_id, scraped, checked_at):
    conn.execute(
        "INSERT INTO price_history (product_id, price, stock_status, checked_at) VALUES (?, ?, ?, ?)",
        (product_id, scraped["price"], scraped["stock_status"], checked_at),
    )
    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
