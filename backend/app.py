import csv
import io
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import login_required, login_user, logout_user

from auth import User, login_manager, verify_credentials
from models import DB_PATH, init_db, insert_price_check, update_product_image
from scraper import STORES, scrape_product, store_domain

load_dotenv()

FRONTEND_FILE = Path(__file__).parent.parent / "prototype" / "dashboard.html"

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # caps CSV import uploads

login_manager.init_app(app)

limiter = Limiter(key_func=get_remote_address, app=app)

init_db()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/")
def index():
    return send_file(FRONTEND_FILE)


@app.route("/api/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request.get_json(silent=True) or {}
    if verify_credentials(data.get("username"), data.get("password")):
        login_user(User())
        return jsonify({"ok": True})
    return jsonify({"error": "Invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/products", methods=["GET"])
@login_required
def list_products():
    db = get_db()
    rows = db.execute("""
        SELECT p.id, p.name, p.url, p.store, p.image_url, p.pinned, ph.price, ph.stock_status, ph.checked_at
        FROM products p
        LEFT JOIN price_history ph ON ph.id = (
            SELECT id FROM price_history
            WHERE product_id = p.id
            ORDER BY checked_at DESC
            LIMIT 1
        )
        ORDER BY p.pinned DESC, p.added_at DESC
    """).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/products/<int:product_id>/pin", methods=["POST"])
@login_required
def pin_product(product_id):
    data = request.get_json(silent=True) or {}
    pinned = data.get("pinned")
    if not isinstance(pinned, bool):
        return jsonify({"error": "pinned must be true or false"}), 400

    db = get_db()
    cursor = db.execute("UPDATE products SET pinned = ? WHERE id = ?", (int(pinned), product_id))
    if cursor.rowcount == 0:
        return jsonify({"error": "Product not found"}), 404
    db.commit()

    return jsonify({"id": product_id, "pinned": pinned})


@app.route("/api/stores", methods=["GET"])
@login_required
def list_stores():
    # Count by URL domain rather than the stored store name, since that name
    # comes from each site's own markup and isn't guaranteed to match.
    db = get_db()
    counts = Counter(store_domain(row["url"]) for row in db.execute("SELECT url FROM products"))
    return jsonify([
        {
            "name": store["name"],
            "domain": store["domain"],
            "url": store["url"],
            "product_count": counts.get(store["domain"], 0),
        }
        for store in STORES
    ])


def csv_safe(value):
    """Scraped text ends up in a spreadsheet, so stop a value that starts
    with a formula character from being run as a formula when opened."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@app.route("/api/export.csv", methods=["GET"])
@login_required
def export_csv():
    db = get_db()
    rows = db.execute("""
        SELECT p.id, p.name, p.store, p.url, ph.checked_at, ph.price, ph.stock_status
        FROM price_history ph
        JOIN products p ON p.id = ph.product_id
        ORDER BY p.id, ph.checked_at
    """).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["product_id", "name", "store", "url", "checked_at", "price", "stock_status"])
    for row in rows:
        writer.writerow([csv_safe(value) for value in row])

    filename = f"price-history-{datetime.now().date().isoformat()}.csv"
    # The BOM makes Excel open the file as UTF-8, so names with special
    # characters display correctly.
    return Response(
        "﻿" + buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


IMPORT_COLUMNS = ("name", "store", "url", "checked_at", "price", "stock_status")
STOCK_STATUSES = {"in_stock", "low_stock", "out_of_stock", "unknown"}


def csv_unsafe(value):
    """Reverse csv_safe() so re-imported names match the originals."""
    if value.startswith("'") and value[1:2] in ("=", "+", "-", "@"):
        return value[1:]
    return value


def parse_import_rows(text):
    """Validate every row of an exported CSV before anything is written.
    Returns (records, errors); errors are human-readable with line numbers."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [col for col in IMPORT_COLUMNS if col not in (reader.fieldnames or [])]
    if missing:
        return [], [f"Missing column(s): {', '.join(missing)}"]

    records, errors = [], []
    for line, row in enumerate(reader, start=2):
        url = (row["url"] or "").strip()
        name = csv_unsafe((row["name"] or "").strip())
        store = csv_unsafe((row["store"] or "").strip())
        if not url or not name or not store:
            errors.append(f"Line {line}: name, store and url are required")
            continue

        try:
            price = float(row["price"])
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"Line {line}: invalid price '{row['price']}'")
            continue

        try:
            checked = datetime.fromisoformat((row["checked_at"] or "").strip())
        except ValueError:
            errors.append(f"Line {line}: invalid checked_at '{row['checked_at']}'")
            continue
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        checked_at = checked.astimezone(timezone.utc).isoformat(timespec="seconds")

        stock_status = (row["stock_status"] or "").strip()
        if stock_status not in STOCK_STATUSES:
            stock_status = "unknown"

        records.append({
            "url": url, "name": name, "store": store,
            "checked_at": checked_at, "price": price, "stock_status": stock_status,
        })

    return records, errors


@app.route("/api/import", methods=["POST"])
@login_required
def import_csv():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose a CSV file to import"}), 400

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"error": "The file isn't a UTF-8 CSV"}), 400

    records, errors = parse_import_rows(text)
    if errors:
        return jsonify({"error": "Nothing was imported. Fix these rows and try again.", "details": errors[:10]}), 400
    if not records:
        return jsonify({"error": "The file has no rows to import"}), 400

    db = get_db()
    # Products are matched by URL (ignoring a trailing slash), not by
    # product_id, because ids differ between databases.
    product_ids = {
        row["url"].rstrip("/"): row["id"]
        for row in db.execute("SELECT id, url FROM products")
    }
    existing_checks = {
        (row["product_id"], row["checked_at"])
        for row in db.execute("SELECT product_id, checked_at FROM price_history")
    }

    first_seen = {}
    for record in records:
        key = record["url"].rstrip("/")
        first_seen[key] = min(first_seen.get(key, record["checked_at"]), record["checked_at"])

    products_created = rows_added = rows_skipped = 0
    for record in records:
        key = record["url"].rstrip("/")
        product_id = product_ids.get(key)
        if product_id is None:
            cursor = db.execute(
                "INSERT INTO products (name, url, store, added_at) VALUES (?, ?, ?, ?)",
                (record["name"], record["url"], record["store"], first_seen[key]),
            )
            product_id = product_ids[key] = cursor.lastrowid
            products_created += 1

        if (product_id, record["checked_at"]) in existing_checks:
            rows_skipped += 1
            continue

        db.execute(
            "INSERT INTO price_history (product_id, price, stock_status, checked_at) VALUES (?, ?, ?, ?)",
            (product_id, record["price"], record["stock_status"], record["checked_at"]),
        )
        existing_checks.add((product_id, record["checked_at"]))
        rows_added += 1

    db.commit()
    return jsonify({
        "products_created": products_created,
        "rows_added": rows_added,
        "rows_skipped": rows_skipped,
    })


@app.route("/api/products", methods=["POST"])
@login_required
def add_product():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    db = get_db()
    existing = db.execute(
        "SELECT id FROM products WHERE rtrim(url, '/') = rtrim(?, '/')", (url,)
    ).fetchone()
    if existing is not None:
        return jsonify({"error": "This product is already being tracked"}), 409

    try:
        scraped = scrape_product(url)
    except Exception as exc:
        return jsonify({"error": f"Could not scrape product: {exc}"}), 400

    if scraped["price"] is None:
        return jsonify({"error": "Could not find a price on that page"}), 400

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cursor = db.execute(
        "INSERT INTO products (name, url, store, added_at, image_url) VALUES (?, ?, ?, ?, ?)",
        (scraped["name"], url, scraped["store"], now, scraped["image_url"]),
    )
    product_id = cursor.lastrowid
    insert_price_check(db, product_id, scraped, now)

    return jsonify({"id": product_id, "url": url, **scraped}), 201


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
@login_required
def delete_product(product_id):
    db = get_db()
    product = db.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return jsonify({"error": "Product not found"}), 404

    db.execute("DELETE FROM price_history WHERE product_id = ?", (product_id,))
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()

    return jsonify({"ok": True})


@app.route("/api/products/<int:product_id>/history", methods=["GET"])
@login_required
def product_history(product_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return jsonify({"error": "Product not found"}), 404

    rows = db.execute(
        "SELECT price, stock_status, checked_at FROM price_history WHERE product_id = ? ORDER BY checked_at",
        (product_id,),
    ).fetchall()

    return jsonify({
        "product": dict(product),
        "history": [dict(row) for row in rows],
    })


@app.route("/api/products/<int:product_id>/refresh", methods=["POST"])
@login_required
def refresh_product(product_id):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return jsonify({"error": "Product not found"}), 404

    try:
        scraped = scrape_product(product["url"])
    except Exception as exc:
        return jsonify({"error": f"Could not scrape product: {exc}"}), 400

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_price_check(db, product_id, scraped, now)
    update_product_image(db, product_id, scraped["image_url"])

    return jsonify({"id": product_id, "checked_at": now, **scraped})


if __name__ == "__main__":
    app.run(debug=True)
