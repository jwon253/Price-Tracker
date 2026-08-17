import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

AVAILABILITY_TO_STOCK_STATUS = {
    "https://schema.org/InStock": "in_stock",
    "http://schema.org/InStock": "in_stock",
    "https://schema.org/LimitedAvailability": "low_stock",
    "http://schema.org/LimitedAvailability": "low_stock",
    "https://schema.org/OutOfStock": "out_of_stock",
    "http://schema.org/OutOfStock": "out_of_stock",
    "https://schema.org/Discontinued": "out_of_stock",
    "http://schema.org/Discontinued": "out_of_stock",
}


def scrape_product(url):
    """Fetch a product page and read its details from JSON-LD Product schema."""
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
    stock_status = AVAILABILITY_TO_STOCK_STATUS.get(availability, "unknown")

    return {
        "name": product.get("name"),
        "store": store,
        "price": offers.get("price") if offers else None,
        "stock_status": stock_status,
    }


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.pbtech.co.nz/product/AUDROD0010/RODE-NT-USB-Mini-USB-Microphone-35mm-Headphone-Mon"
    )
    print(scrape_product(url))
