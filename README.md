# Price-Tracker

A self-hosted price tracker for one user. Add a product URL and it records the price and stock status. A daily job re-checks every product, and the dashboard charts each product's price history.

**Supported stores:** PB Tech, Computer Lounge, Foot Locker (NZ), Connor (NZ), Briscoes, ExtremePC

Built with Flask, SQLite and a plain HTML/JS frontend.

## Project layout

```
backend/
  app.py               Flask app: serves the dashboard and the JSON API
  auth.py              Single-user login (Flask-Login)
  models.py            SQLite schema and helpers (price_tracker.db)
  scraper.py           Store-specific scrapers
  daily_scrape.py      Re-scrapes every tracked product (run by cron)
  generate_password.py Creates the password hash for .env
  deploy/              systemd service and crontab examples
prototype/
  dashboard.html       The frontend: plain HTML, CSS and JS, no build step
scrape.py              Original PB Tech test script (superseded by backend/scraper.py)
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

Fill in `backend/.env`:

- `AUTH_PASSWORD_HASH`: run `python backend/generate_password.py`
- `SECRET_KEY`: run `python -c "import secrets; print(secrets.token_hex(32))"`

## Run

```bash
cd backend
python app.py
```

Open http://127.0.0.1:5000. The database is created on first run.

## Deploy

The files in `backend/deploy/` assume the repo is at `/home/jay/Price-Tracker`. Change the paths and user to match your server.

**Web app (systemd + gunicorn):**

```bash
pip install gunicorn
sudo cp backend/deploy/price-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now price-tracker
```

gunicorn listens on `127.0.0.1:5000`. Put a reverse proxy such as nginx or Caddy in front of it to serve the app over HTTPS.

**Daily scrape (cron):**

```bash
crontab -e   # paste the line from backend/deploy/crontab.txt
```

The job starts at 6:30am, waits a random 0–90 minutes, then scrapes. Output goes to `backend/daily_scrape.log`.

## API

All endpoints except `/api/login` require you to be logged in (session cookie).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/login` | `{"username", "password"}`, limited to 5 per minute |
| `POST` | `/api/logout` | End the session |
| `GET` | `/api/stores` | Supported stores with the number of products tracked from each |
| `GET` | `/api/export.csv` | Download every recorded price check as a CSV file |
| `POST` | `/api/import` | Upload an exported CSV (`file` field). Products are matched by URL, rows already present are skipped, and nothing is imported if any row is invalid |
| `GET` | `/api/products` | All products with their latest price and stock status |
| `POST` | `/api/products` | `{"url"}`: scrape and start tracking a product |
| `DELETE` | `/api/products/<id>` | Stop tracking a product and delete its history |
| `GET` | `/api/products/<id>/history` | The product plus every recorded price check |
| `POST` | `/api/products/<id>/refresh` | Scrape the product now |

## Adding a store

Add a `scrape_<store>(url)` function to `backend/scraper.py` that returns `name`, `store`, `price`, `stock_status` and `image_url`. Then add it to the `STORES` list at the bottom of that file. The scraper and the Stores page both read from that list.
