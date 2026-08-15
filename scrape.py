import json
import re
import requests
from bs4 import BeautifulSoup

url = "https://www.pbtech.co.nz/product/AUDSNP700065/Sennheiser-Pro-Profile-USB-Microphone---USB-C-powe"
# url = "https://www.pbtech.co.nz/product/AUDROD0010/RODE-NT-USB-Mini-USB-Microphone-35mm-Headphone-Mon"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# 1) Try promo price from page text ("With promo code $XXX.XX")
promo_prices = re.findall(
    r"With promo code\s*\$(\d+\.\d{1})", soup.get_text()
)
if promo_prices:
    # Multiple matches: ex-GST and inc-GST. The highest is inc GST.
    price = max(promo_prices, key=float)
    print(f"Promo price: ${price}")
else:
    None
    # 2) Fall back to JSON-LD standard price
    price = None
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
        except (TypeError, ValueError):
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if entry.get("@type") == "Product":
                offers = entry.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if offers:
                    price = offers.get("price")
                break
        if price is not None:
            break

    if price is not None:
        print(f"Price: ${price}")
    else:
        print("Price not found")