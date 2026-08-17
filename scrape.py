import json
import re
from datetime import date
import requests
from bs4 import BeautifulSoup

# url = "https://www.pbtech.co.nz/product/AUDSNP700065/Sennheiser-Pro-Profile-USB-Microphone---USB-C-powe"
# url = "https://www.pbtech.co.nz/product/AUDROD0010/RODE-NT-USB-Mini-USB-Microphone-35mm-Headphone-Mon"
url = "https://www.pbtech.co.nz/product/CABUGR70645/UGREEN-UG-70645-5A---100W-PD-USB-C-Cable---2m---Bl"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Pull the Product entry once from JSON-LD; name and price both read from it.
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

offers = product.get("offers") if product else None
if isinstance(offers, list):
    offers = offers[0] if offers else None

name = product.get("name") if product else None
seller = offers.get("seller") if offers else None
store = seller.get("name") if isinstance(seller, dict) else None
timestamp = date.today().strftime("%d/%m/%Y")

print(f"Date: {timestamp}")

if store:
    print(f"Store: {store}")
else:
    print("Store not found")

if name:
    short_name = " ".join(name.split()[:5])
    print(f"Product: {short_name}")
else:
    print("Product name not found")

# 1) Try promo price from page text ("With promo code $XXX.XX")
promo_prices = re.findall(
    r"With promo code\s*\$(\d+\.\d{1})", soup.get_text()
)
if promo_prices:
    # Multiple matches: ex-GST and inc-GST. The highest is inc GST.
    price = max(promo_prices, key=float)
    print(f"Promo price: ${price}")
else:
    # 2) Fall back to the JSON-LD offer price
    price = offers.get("price") if offers else None
    if price is not None:
        print(f"Price: ${price}")
    else:
        print("Price not found")