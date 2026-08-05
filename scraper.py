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
    
    api_url = "https://api.scrapingant.com/v2/general"
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

def is_old_price_element(element):
    # Check parent chain up to 4 levels
    curr = element
    for _ in range(4):
        if not curr or curr.name == '[document]':
            break
        if curr.name in ['del', 's', 'strike']:
            return True
        classes = curr.get('class', [])
        if classes:
            class_str = " ".join(classes).lower()
            if any(k in class_str for k in ['was', 'old', 'original', 'compare', 'strike', 'crossed', 'was-price', 'oldprice']):
                return True
        style = curr.get('style', '')
        if style and 'line-through' in style.lower():
            return True
        curr = curr.parent
    return False

def extract_prices_from_html(soup_element):
    price_candidates = []
    
    # We find all text nodes in the element
    text_nodes = soup_element.find_all(text=True)
    
    for node in text_nodes:
        txt = node.strip()
        if re.search(r'\d+', txt):
            # Check up to 4 parent levels for the word "aed"
            has_currency = False
            curr_parent = node.parent
            for _ in range(4):
                if curr_parent and curr_parent.name != '[document]':
                    if 'aed' in curr_parent.get_text().lower():
                        has_currency = True
                        break
                    curr_parent = curr_parent.parent
                else:
                    break
            
            # If it has currency, extract the value
            if has_currency:
                val = clean_price(txt)
                if not val:
                    # Try to extract numbers from the text using regex directly
                    match = re.search(r'\d+(?:\.\d+)?', txt)
                    if match:
                        val = f"{float(match.group(0)):.2f}"
                
                if val:
                    is_old = is_old_price_element(node.parent)
                    price_candidates.append((float(val), is_old))
                    
    # Sort and remove duplicates
    unique_candidates = []
    seen = set()
    for val, is_old in price_candidates:
        if val not in seen:
            seen.add(val)
            unique_candidates.append((val, is_old))
            
    if not unique_candidates:
        return None, None
        
    rsp = None
    list_price = None
    
    if len(unique_candidates) == 1:
        rsp = f"{unique_candidates[0][0]:.2f}"
    else:
        old_prices = [val for val, is_old in unique_candidates if is_old]
        active_prices = [val for val, is_old in unique_candidates if not is_old]
        
        if old_prices and active_prices:
            list_price = f"{max(old_prices):.2f}"
            rsp = f"{min(active_prices):.2f}"
        else:
            vals = sorted([val for val, _ in unique_candidates])
            rsp = f"{vals[0]:.2f}"
            list_price = f"{vals[-1]:.2f}"
            
    return rsp, list_price

def scrape_amazon(barcode):
    log(f"Amazon: Searching barcode {barcode}...")
    search_url = f"https://www.amazon.ae/s?k={barcode}"
    content, error = query_scraperant(search_url)
    
    if error:
        log(f"Amazon Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Select first non-ad product result card
    items = [item for item in soup.select("div[data-asin]") if item.get("data-asin")]
    
    if not items:
        log("Amazon: Product not found.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
        
    first_item = items[0]
    
    # Extract RSP with specific selectors
    rsp = None
    price_whole = first_item.select_one(".a-price-whole")
    price_fraction = first_item.select_one(".a-price-fraction")
    if price_whole:
        whole_str = price_whole.text.strip().replace('\n', '').replace(' ', '')
        fraction_str = price_fraction.text.strip() if price_fraction else "00"
        rsp = clean_price(f"{whole_str}.{fraction_str}")
    else:
        offscreen = first_item.select_one(".a-price .a-offscreen")
        if offscreen:
            rsp = clean_price(offscreen.text)
            
    # Extract List Price with specific selectors
    list_price = None
    list_tag = first_item.select_one(".a-text-price span.a-offscreen") or first_item.select_one(".a-text-price")
    if list_tag:
        list_price = clean_price(list_tag.text)
        
    # Fallback to class-agnostic price parser if RSP wasn't found
    if not rsp:
        parsed_rsp, parsed_list = extract_prices_from_html(first_item)
        if parsed_rsp:
            rsp = parsed_rsp
            if not list_price:
                list_price = parsed_list

    # Extract direct link
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

def scrape_noon(barcode):
    log(f"Noon: Searching barcode {barcode}...")
    search_url = f"https://www.noon.com/uae-en/search/?q={barcode}"
    cookies = "noon_country=ae;noon_language=en;noon_geohash=thrq1"
    content, error = query_scraperant(search_url, cookies=cookies)
    
    if error:
        log(f"Noon Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Check if redirected directly to a product page
    is_product_page = soup.select_one('span[class*="priceNow"]') or soup.select_one('div[class*="ProductHeader"]')
    
    if is_product_page:
        log("Noon: Redirected directly to product page.")
        rsp, list_price = extract_prices_from_html(soup)
        return {"rsp": rsp, "list_price": list_price, "url": search_url, "status": "Success" if rsp else "Not Found"}
        
    # Search grid
    cards = soup.select("a[href*='/p/']")
    if not cards:
        log("Noon: Product not found in search grid.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
        
    first_card = cards[0]
    rsp, list_price = extract_prices_from_html(first_card)
    
    product_url = search_url
    href = first_card.get("href")
    if href:
        product_url = "https://www.noon.com" + href
        
    log(f"Noon Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
    return {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success" if rsp else "Not Found"}

def scrape_noon_minutes(barcode):
    log(f"Noon Minutes: Searching barcode {barcode}...")
    search_url = f"https://minutes.noon.com/uae-en/search?q={barcode}"
    cookies = "noon_country=ae;noon_language=en;noon_geohash=thrq1"
    content, error = query_scraperant(search_url, cookies=cookies)
    
    if error:
        log(f"Noon Minutes Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Extract from search results
    cards = soup.select("a[href*='product']") or soup.select("a[href*='/p/']") or soup.select("div[class*='ProductCard']")
    
    if not cards:
        # Fallback: check if the page has any price elements directly in the body
        rsp, list_price = extract_prices_from_html(soup)
        if rsp:
            log(f"Noon Minutes Success (Fallback): RSP={rsp}, List={list_price}")
            return {"rsp": rsp, "list_price": list_price, "url": search_url, "status": "Success"}
            
        log("Noon Minutes: Product not found.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Stocked"}
        
    first_card = cards[0]
    rsp, list_price = extract_prices_from_html(first_card)
    
    product_url = search_url
    href = first_card.get("href") if hasattr(first_card, 'get') else None
    if href:
        product_url = "https://minutes.noon.com" + href if href.startswith("/") else href
        
    log(f"Noon Minutes Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
    return {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success" if rsp else "Not Stocked"}

def scrape_talabat(barcode):
    log(f"Talabat: Searching barcode {barcode}...")
    search_url = f"https://www.talabat.com/ae/en/search?q={barcode}"
    cookies = f"latitude={DUBAI_LAT};longitude={DUBAI_LON};cityId={DUBAI_CITY_ID};areaId={DUBAI_AREA_ID}"
    content, error = query_scraperant(search_url, cookies=cookies)
    
    if error:
        log(f"Talabat Error: {error}")
        return {"rsp": None, "list_price": None, "url": search_url, "status": error}
        
    soup = BeautifulSoup(content, 'html.parser')
    
    # Try finding items
    cards = soup.select("[class*='ProductCard']") or soup.select("[class*='item']") or soup.select(".product-card")
    
    if not cards:
        # Fallback: Find elements containing currency strings
        price_elements = soup.find_all(text=re.compile(r'\d+(?:\.\d+)?\s*AED|AED\s*\d+(?:\.\d+)?'))
        cards = []
        for el in price_elements:
            parent = el.parent
            for _ in range(5):
                if parent and ('card' in parent.get('class', [""])[0].lower() or 'item' in parent.get('class', [""])[0].lower() or parent.name == 'a'):
                    cards.append(parent)
                    break
                if parent:
                    parent = parent.parent
                    
    if not cards:
        log("Talabat: Product not found.")
        return {"rsp": None, "list_price": None, "url": search_url, "status": "Not Found"}
        
    first_card = cards[0]
    rsp, list_price = extract_prices_from_html(first_card)
    
    product_url = search_url
    link_tag = first_card.select_one("a") or first_card if first_card.name == "a" else None
    if link_tag and link_tag.get("href"):
        href = link_tag["href"]
        product_url = "https://www.talabat.com" + href if href.startswith("/") else href

    log(f"Talabat Success: RSP={rsp or 'None'}, List={list_price or 'None'}")
    return {"rsp": rsp, "list_price": list_price, "url": product_url, "status": "Success" if rsp else "Not Found"}

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
        
        noon = scrape_noon(barcode)
        time.sleep(5)
        
        noon_minutes = scrape_noon_minutes(barcode)
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
