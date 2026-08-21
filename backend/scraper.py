import json
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def scrape_product(url):
    """Dispatch to a store-specific scraper based on the URL's domain.

    Each store renders and structures its product data differently (some
    embed schema.org JSON-LD, others are JS-rendered SPAs backed by a
    GraphQL API), so each gets its own dedicated scraper rather than one
    generalized parser trying to handle every shape.
    """
    domain = urlparse(url).netloc.lower().removeprefix("www.")

    if domain == "pbtech.co.nz":
        return scrape_pbtech(url)
    if domain == "connor.com.au":
        return scrape_connor(url)

    raise ValueError(f"No scraper available for '{domain}'")


def extract_image_url(image):
    """JSON-LD "image" can be a URL string, a list of URL strings, an
    ImageObject dict, or a list of those — normalize to a single URL."""
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        return image.get("url")
    if isinstance(image, str):
        return image
    return None


# ---------- PB Tech ----------

PBTECH_AVAILABILITY_TO_STOCK_STATUS = {
    "https://schema.org/InStock": "in_stock",
    "http://schema.org/InStock": "in_stock",
    "https://schema.org/LimitedAvailability": "low_stock",
    "http://schema.org/LimitedAvailability": "low_stock",
    "https://schema.org/OutOfStock": "out_of_stock",
    "http://schema.org/OutOfStock": "out_of_stock",
    "https://schema.org/Discontinued": "out_of_stock",
    "http://schema.org/Discontinued": "out_of_stock",
}


def scrape_pbtech(url):
    """PB Tech pages embed their product details as schema.org JSON-LD."""
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    product = None
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
        except (TypeError, ValueError):
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if entry.get("@type") == "Product":
                product = entry
                break
        if product is not None:
            break

    if product is None:
        raise ValueError(f"No Product JSON-LD found at {url}")

    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None

    seller = offers.get("seller") if offers else None
    store = seller.get("name") if isinstance(seller, dict) else None

    availability = offers.get("availability") if offers else None
    stock_status = PBTECH_AVAILABILITY_TO_STOCK_STATUS.get(availability, "unknown")

    regular_price = offers.get("price") if offers else None
    price = extract_pbtech_promo_price(soup)
    if price is None:
        price = regular_price

    return {
        "name": product.get("name"),
        "store": store,
        "price": price,
        "stock_status": stock_status,
        "image_url": extract_image_url(product.get("image")),
    }


def extract_pbtech_promo_price(soup):
    """PB Tech often masks the real selling price behind a "with promo
    code" banner instead of showing it as the plain listed price. When
    present, that's the price a shopper actually pays, so prefer it over
    the JSON-LD regular price. Returns None if no promo is running (the
    banner then just reads "PB Tech price" with no dollar amount)."""
    label = soup.find("div", class_="item-price-label")
    if label is None:
        return None

    ginc = label.find("div", class_="ginc")
    if ginc is None:
        return None

    amount = ginc.find("span", class_="fw-semibold")
    if amount is None:
        return None

    text = amount.get_text(strip=True).replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


# ---------- Connor ----------

CONNOR_GRAPHQL_URL = "https://mcprod2.connor.com.au/graphql"

# Connor's site is a JS-rendered SPA with no server-rendered product data,
# so instead of a headless browser we call the Magento GraphQL API it uses
# internally. Store code is derived from the locale segment of the URL
# (e.g. /nz/... -> "cr_nz"); add more locales here as they're confirmed.
CONNOR_LOCALE_STORE_CODES = {
    "nz": "cr_nz",
}

CONNOR_STOCK_STATUS = {
    "IN_STOCK": "in_stock",
    "OUT_OF_STOCK": "out_of_stock",
}

CONNOR_PRODUCT_QUERY = """
query GetProduct($urlKey: String!) {
    products(filter: { url_key: { eq: $urlKey } }) {
        items {
            name
            stock_status
            small_image { url }
            price_range {
                minimum_price {
                    final_price { value }
                }
            }
        }
    }
}
"""


def scrape_connor(url):
    """Connor renders product pages client-side with no server-rendered
    data, so this queries the Magento GraphQL API the storefront itself
    calls, instead of scraping HTML."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError(f"Could not parse a product URL from {url}")

    locale, url_key = path_parts[0], path_parts[-1]
    store_code = CONNOR_LOCALE_STORE_CODES.get(locale)
    if store_code is None:
        raise ValueError(f"Unsupported Connor locale '{locale}' in {url}")

    response = requests.post(
        CONNOR_GRAPHQL_URL,
        json={"query": CONNOR_PRODUCT_QUERY, "variables": {"urlKey": url_key}},
        headers={"Content-Type": "application/json", "Store": store_code},
        timeout=20,
    )
    response.raise_for_status()

    items = response.json().get("data", {}).get("products", {}).get("items") or []
    if not items:
        raise ValueError(f"No product found for {url}")

    product = items[0]
    price = (
        product.get("price_range", {})
        .get("minimum_price", {})
        .get("final_price", {})
        .get("value")
    )

    return {
        "name": product.get("name"),
        "store": "Connor",
        "price": price,
        "stock_status": CONNOR_STOCK_STATUS.get(product.get("stock_status"), "unknown"),
        "image_url": product.get("small_image", {}).get("url"),
    }


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.pbtech.co.nz/product/AUDROD0010/RODE-NT-USB-Mini-USB-Microphone-35mm-Headphone-Mon"
    )
    print(scrape_product(url))
