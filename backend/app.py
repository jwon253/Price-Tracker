import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import login_required, login_user, logout_user

from auth import User, login_manager, verify_credentials
from models import DB_PATH, init_db, insert_price_check, update_product_image
from scraper import scrape_product

load_dotenv()

FRONTEND_FILE = Path(__file__).parent.parent / "prototype" / "dashboard.html"

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

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
        SELECT p.id, p.name, p.url, p.store, p.image_url, ph.price, ph.stock_status, ph.checked_at
        FROM products p
        LEFT JOIN price_history ph ON ph.id = (
            SELECT id FROM price_history
            WHERE product_id = p.id
            ORDER BY checked_at DESC
            LIMIT 1
        )
        ORDER BY p.added_at DESC
    """).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/products", methods=["POST"])
@login_required
def add_product():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "url is required"}), 400

    try:
        scraped = scrape_product(url)
    except Exception as exc:
        return jsonify({"error": f"Could not scrape product: {exc}"}), 400

    if scraped["price"] is None:
        return jsonify({"error": "Could not find a price on that page"}), 400

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db = get_db()
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
