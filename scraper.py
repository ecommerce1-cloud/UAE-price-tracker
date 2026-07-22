import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Central configuration
API_KEY = os.environ.get("SCRAPINGANT_API_KEY", "")
CAREEM_TOKEN = os.environ.get("CAREEM_TOKEN", "")

# Dubai Coordinates (Downtown Dubai - default location for high stock availability)
DUBAI_LAT = "25.2048"
DUBAI_LON = "55.2708"
DUBAI_CITY_ID = "1"
DUBAI_AREA_ID = "1"

# Logging list to store log lines for the UI console
run_logs = []

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    run_logs.append(formatted_msg)

def clean_price(price_str):
    if not price_str:
        return None
    # Remove commas and spaces
    cleaned = price_str.replace(',', '').strip()
    # Extract first decimal number (e.g. "AED 12.50" -> "12.50")
    match = re.search(r'\d+(?:\.\d+)?', cleaned)
    if match:
        return f"{float(match.group(0)):.2f}"
    return None

def query_scraperant(target_url, cookies=None):
    if not API_KEY:
        return None, "ScraperAnt API Key missing. Please set the SCRAPINGANT_API_KEY secret."
    
    api_url = "https://api.scraperant.com/v2/general"
    params = {
        "url": target_url,
        "x-api-key": API_KEY,
        "browser": "true",
        "proxy_type": "residential",
        "proxy_country": "ae"
    }
    
    if cookies:
        params["cookies"] = cookies

    try:
        response = requests.get(api_url, params=params, timeout=75)
        if response.status_code == 200:
            return response.content, None
        else:
            return None, f"HTTP Error {response.status_code}"
    except Exception as e:
        return None, f"Connection timeout: {str(e)}"

def scrape_amazon(barcode):
    log(f"Amazon: Searching barcode {barcode}...")
    search_url = f"https://www.amazon.ae/s?k={barcode}"
    content, error = query_scraperant(search_url)
    
    if error:
        log(f"Amazon Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Select first non-ad product result card
    # Amazon search results container can be matched by div[data-asin] where data-asin is present and not empty
    items = [item for item in soup.select("div[data-asin]") if item.get("data-asin")]
    
    if not items:
        log("Amazon: Product not found.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
        
    first_item = items[0]
    
    # 1. Extract RSP
    rsp = None
    price_whole = first_item.select_one(".a-price-whole")
    price_fraction = first_item.select_one(".a-price-fraction")
    if price_whole:
        whole_str = price_whole.text.strip().replace('\n', '').replace(' ', '')
        fraction_str = price_fraction.text.strip() if price_fraction else "00"
        rsp = clean_price(f"{whole_str}.{fraction_str}")
    else:
        # Fallback RSP selector
        offscreen = first_item.select_one(".a-price .a-offscreen")
        if offscreen:
            rsp = clean_price(offscreen.text)
            
    # 2. Extract List Price ( crossed out price )
    list_price = None
    list_tag = first_item.select_one(".a-text-price span.a-offscreen") or first_item.select_one(".a-text-price")
    if list_tag:
        list_price = clean_price(list_tag.text)
        
    # 3. Extract direct link
    product_url = search_url
    link_tag = first_item.select_one("h2 a.a-link-normal") or first_item.select_one("a.a-link-normal")
    if link_tag and link_tag.get("href"):
        href = link_tag["href"]
        if href.startswith("/"):
            product_url = "https://www.amazon.ae" + href
        elif href.startswith("http"):
            product_url = href

    log(f"Amazon Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
    return {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success"}

def scrape_noon_and_minutes(barcode):
    log(f"Noon & Noon Minutes: Searching barcode {barcode}...")
    search_url = f"https://www.noon.com/uae-en/search/?q={barcode}"
    
    # Set Noon localization cookie to target Dubai Marina/Downtown
    # 'noon_geohash' can be estimated for Dubai center: 'thrq1' or similar
    cookies = f"noon_country=ae;noon_language=en;noon_geohash=thrq1"
    content, error = query_scraperant(search_url, cookies=cookies)
    
    if error:
        log(f"Noon Error: {error}")
        return (
            {"rsp": None, "list_price": None, "url": search_url, "status": error},
            {"rsp": None, "list_price": None, "url": search_url, "status": error}
        )
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Check if we were redirected directly to a product page or stayed on search page
    # Direct product pages usually have a class starting with 'priceNow' or 'productHeader'
    is_product_page = soup.select_one('span[class*="priceNow"]') or soup.select_one('div[class*="ProductHeader"]')
    
    noon_data = {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
    minutes_data = {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
    
    if is_product_page:
        log("Noon: Redirected directly to product page.")
        # RSP
        price_now = soup.select_one('span[class*="priceNow"]') or soup.select_one('.amount')
        rsp = clean_price(price_now.text) if price_now else None
        
        # List Price
        was_price = soup.select_one('span[class*="was"]') or soup.select_one('span[class*="oldPrice"]')
        list_price = clean_price(was_price.text) if was_price else None
        
        noon_data = {"rsp": str(rsp) if rsp else None, "list_price": str(list_price) if list_price else None, "url": search_url, "status": "Success"}
        
        # Check if Noon Minutes is available on product page
        # Usually it has an icon/badge or a section like "Delivery via noon Minutes"
        minutes_section = soup.find(text=re.compile("noon minutes", re.IGNORECASE)) or soup.select_one('div[class*="minutes"]')
        if minutes_section:
            # On product page, the price is generally the same or can be fetched. Fallback to same RSP.
            minutes_data = {"rsp": str(rsp) if rsp else None, "list_price": str(list_price) if list_price else None, "url": search_url, "status": "Success"}
        else:
            minutes_data = {"rsp": None, "list_price": None, "url": search_url, "status": "Not Stocked"}
            
    else:
        # We are on the search grid list
        # Grid items contain anchor tags directing to product page '/p/'
        cards = [card for card in soup.select("a[href*='/p/']")]
        if not cards:
            log("Noon: Product not found in search grid.")
            return noon_data, minutes_data
            
        first_card = cards[0]
        
        # RSP
        price_tag = first_card.select_one('.amount') or first_card.select_one('[class*="priceNow"]')
        rsp = clean_price(price_tag.text) if price_tag else None
        
        # List Price
        was_tag = first_card.select_one('.was') or first_card.select_one('[class*="oldPrice"]')
        list_price = clean_price(was_tag.text) if was_tag else None
        
        # Product URL
        product_url = search_url
        href = first_card.get("href")
        if href:
            product_url = "https://www.noon.com" + href
            
        noon_data = {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success"}
        
        # Check if the grid item card has a Noon Minutes badge
        card_text = first_card.text.lower()
        is_minutes = "minutes" in card_text or "15 mins" in card_text or "instant" in card_text
        
        if is_minutes:
            # If it's a minutes delivery item, RSP applies to minutes
            minutes_data = {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success"}
        else:
            # Let's search other cards to see if there is a minutes option for the same barcode
            found_minutes = False
            for card in cards[1:4]: # check next few cards
                if "minutes" in card.text.lower() or "15 mins" in card.text.lower():
                    m_price_tag = card.select_one('.amount') or card.select_one('[class*="priceNow"]')
                    m_rsp = clean_price(m_price_tag.text) if m_price_tag else None
                    m_was = card.select_one('.was') or card.select_one('[class*="oldPrice"]')
                    m_list = clean_price(m_was.text) if m_was else None
                    
                    m_href = card.get("href")
                    m_url = "https://www.noon.com" + m_href if m_href else search_url
                    
                    minutes_data = {"rsp": m_rsp, "list_price": m_list, "url": m_url, "status": "Success"}
                    found_minutes = True
                    break
            if not found_minutes:
                minutes_data = {"rsp": None, "list_price": None, "url": search_url, "status": "Not Stocked"}

    log(f"Noon Success: RSP={noon_data['rsp'] or 'None'}, List={noon_data['list_price'] or 'None'}")
    log(f"Noon Minutes Success: RSP={minutes_data['rsp'] or 'None'}, Status={minutes_data['status']}")
    return noon_data, minutes_data

def scrape_talabat(barcode):
    log(f"Talabat: Searching barcode {barcode}...")
    search_url = f"https://www.talabat.com/ae/en/grocery/search?q={barcode}"
    
    # Inject coordinate cookies into ScraperAnt to set the delivery location to Downtown Dubai
    cookies = f"latitude={DUBAI_LAT};longitude={DUBAI_LON};cityId={DUBAI_CITY_ID};areaId={DUBAI_AREA_ID}"
    content, error = query_scraperant(search_url, cookies=cookies)
    
    if error:
        log(f"Talabat Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Parse Talabat search results
    # Items are usually listed in a flex/grid layout
    items = soup.select("[class*='ProductCard']") or soup.select("[class*='item']") or soup.select(".product-card")
    if not items:
        # Fallback: check if any elements contain price with AED
        items = [el.parent for el in soup.find_all(text=re.compile(r'\d+\.\d+\s*AED|AED\s*\d+\.\d+')) if el.parent]
        
    if not items:
        log("Talabat: Product not found.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
        
    first_item = items[0]
    
    # RSP (Current Selling Price)
    price_tag = first_item.select_one(".price") or first_item.select_one("[class*='price']") or first_item.select_one("[class*='Price']")
    rsp = clean_price(price_tag.text) if price_tag else None
    
    # List Price (Crossed out old price)
    list_price = None
    old_price_tag = first_item.select_one(".old-price") or first_item.select_one(".strike") or first_item.select_one("[class*='oldPrice']") or first_item.select_one("[class*='wasPrice']")
    if old_price_tag:
        list_price = clean_price(old_price_tag.text)
        
    # Product URL
    product_url = search_url
    link_tag = first_item.select_one("a") or first_item if first_item.name == "a" else None
    if link_tag and link_tag.get("href"):
        href = link_tag["href"]
        product_url = "https://www.talabat.com" + href if href.startswith("/") else href

    log(f"Talabat Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
    return {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success"}

def scrape_careem(barcode):
    log(f"Careem Quik: Searching barcode {barcode}...")
    if not CAREEM_TOKEN:
        log("Careem Error: Session Token is missing. Skipping.")
        return {"rsp": None, "list_price": None, "url": "https://www.careem.com", "status": "Token Missing"}
        
    api_url = "https://api.careem.com/grocery/v1/search"
    headers = {
        "Authorization": f"Bearer {CAREEM_TOKEN}",
        "Content-Type": "application/json",
        "x-location-latitude": DUBAI_LAT,
        "x-location-longitude": DUBAI_LON,
        "User-Agent": "Careem/10.0.0 (iPhone; iOS 16.0; Scale/3.00)"
    }
    payload = {
        "query": barcode,
        "latitude": float(DUBAI_LAT),
        "longitude": float(DUBAI_LON),
        "page": 1,
        "limit": 10
    }
    
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=20)
        if response.status_code != 200:
            log(f"Careem API Error: Status {response.status_code}")
            return {"rsp": None, "list_price": None, "url": "https://www.careem.com", "status": f"HTTP {response.status_code}"}
            
        data = response.json()
        products = data.get("products", []) or data.get("data", {}).get("products", [])
        
        if not products:
            log("Careem: Product not found.")
            return {"rsp": None, "list_price": None, "url": "https://www.careem.com", "status": "Not Found"}
            
        first_prod = products[0]
        
        # Parse prices
        # Some API returns float directly, others in subunit (cents/fils). Check size.
        raw_price = first_prod.get("price") or first_prod.get("selling_price") or first_prod.get("discounted_price")
        raw_list = first_prod.get("original_price") or first_prod.get("compare_at_price") or first_prod.get("list_price")
        
        rsp = None
        if raw_price:
            price_val = float(raw_price)
            if price_val > 500: # heuristic: if price > 500, it's likely in fils (subunits)
                price_val = price_val / 100.0
            rsp = f"{price_val:.2f}"
            
        list_price = None
        if raw_list:
            list_val = float(raw_list)
            if list_val > 500:
                list_val = list_val / 100.0
            list_price = f"{list_val:.2f}"
            
        # Deeplink url
        url = first_prod.get("share_url") or first_prod.get("deeplink") or "https://www.careem.com"
        
        log(f"Careem Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
        return {"rsp": rsp, "list_price": list_price, "url": url, "status": "Success"}
        
    except Exception as e:
        log(f"Careem Error: {str(e)}")
        return {"rsp": None, "list_price": None, "url": "https://www.careem.com", "status": f"Error: {str(e)}"}

def run():
    global run_logs
    run_logs = []
    log("Starting Daily Price Comparison Scraper...")
    
    # Read barcodes list
    barcodes_file = "barcodes.json"
    if not os.path.exists(barcodes_file):
        log(f"Error: {barcodes_file} does not exist. Creating with default template.")
        # Fallback creation
        default_barcodes = [{"barcode": "5056141881928", "name": "Default Product"}]
        with open(barcodes_file, "w") as f:
            json.dump(default_barcodes, f, indent=2)
            
    with open(barcodes_file, "r") as f:
        barcodes_list = json.load(f)
        
    log(f"Loaded {len(barcodes_list)} products to track.")
    
    results = []
    
    for item in barcodes_list:
        barcode = item["barcode"]
        name = item["name"]
        log("-" * 50)
        log(f"Processing Product: {name} (Barcode: {barcode})")
        
        # Scrape each platform
        amazon = scrape_amazon(barcode)
        time.sleep(5) # Polite throttle delay
        
        noon, noon_minutes = scrape_noon_and_minutes(barcode)
        time.sleep(5)
        
        talabat = scrape_talabat(barcode)
        time.sleep(5)
        
        careem = scrape_careem(barcode)
        
        results.append({
            "barcode": barcode,
            "name": name,
            "prices": {
                "amazon": amazon,
                "noon": noon,
                "noon_minutes": noon_minutes,
                "talabat": talabat,
                "careem": careem
            }
        })
        log(f"Finished product: {name}")
        time.sleep(10) # Polite delay between products
        
    # Save output
    output_data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %I:%M %p Dubai Time"),
        "log": run_logs,
        "products": results
    }
    
    with open("prices.json", "w") as f:
        json.dump(output_data, f, indent=2)
        
    log("Scraper completed. Saved outputs to prices.json.")

if __name__ == "__main__":
    run()
