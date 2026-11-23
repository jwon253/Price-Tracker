import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from models import DB_PATH, init_db, insert_price_check, update_product_image
from scraper import scrape_product

MIN_DELAY_SECONDS = 0
MAX_DELAY_SECONDS = 60

# Cron triggers this at a fixed time, but always starting at the exact same
# time every day is itself a bot-like signature. Sleeping a random amount
# before doing anything spreads the actual scrape start across a window
# instead of a fixed instant.
STARTUP_JITTER_MAX_SECONDS = 90 * 60

# Past products are only re-checked about once a week. The interval is a bit
# under 7 days because the start time jitters, so a check from last week's
# run is always due by the same weekday.
PAST_PRODUCT_INTERVAL = timedelta(days=6, hours=12)


def is_due(product, now):
    if not product["past"] or product["last_checked"] is None:
        return True
    last = datetime.fromisoformat(product["last_checked"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last >= PAST_PRODUCT_INTERVAL


def run():
    startup_delay = random.uniform(0, STARTUP_JITTER_MAX_SECONDS)
    print(f"[wait] startup jitter: sleeping {startup_delay / 60:.1f} min before starting")
    time.sleep(startup_delay)

    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT p.id, p.name, p.url, p.past,
               (SELECT MAX(checked_at) FROM price_history WHERE product_id = p.id) AS last_checked
        FROM products p
    """).fetchall()
    now = datetime.now(timezone.utc)
    products = [row for row in rows if is_due(row, now)]
    skipped = len(rows) - len(products)
    if skipped:
        print(f"[info] {skipped} past product(s) not due for their weekly check")

    for i, product in enumerate(products):
        if i > 0:
            delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
            print(f"[wait] sleeping {delay / 60:.1f} min before next request")
            time.sleep(delay)

        try:
            scraped = scrape_product(product["url"])
        except Exception as exc:
            print(f"[skip] {product['name']}: {exc}")
            continue

        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        insert_price_check(conn, product["id"], scraped, checked_at)
        update_product_image(conn, product["id"], scraped["image_url"])
        print(f"[ok] {product['name']}: ${scraped['price']} ({scraped['stock_status']})")

    conn.close()


if __name__ == "__main__":
    run()
