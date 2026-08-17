import sqlite3
from datetime import datetime, timezone

from models import DB_PATH, init_db, insert_price_check
from scraper import scrape_product


def run():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    products = conn.execute("SELECT id, name, url FROM products").fetchall()

    for product in products:
        try:
            scraped = scrape_product(product["url"])
        except Exception as exc:
            print(f"[skip] {product['name']}: {exc}")
            continue

        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        insert_price_check(conn, product["id"], scraped, checked_at)
        print(f"[ok] {product['name']}: ${scraped['price']} ({scraped['stock_status']})")

    conn.close()


if __name__ == "__main__":
    run()
