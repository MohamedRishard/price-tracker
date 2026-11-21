import json
import logging
import re
import time
from typing import Optional, Tuple
from bs4 import BeautifulSoup
import httpx

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-LK,en;q=0.9,en-US;q=0.8",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

AUTO_PRICE_SELECTORS = [
    # 1. Dedicated Sale / Deal Price elements (highest priority discounted prices)
    ".sell-price",
    ".selling-price",
    ".special-price",
    ".final-price",
    ".sale-price",
    ".price-current",
    ".actual-price",
    ".detail-price-con .sell-price",
    # 2. Canonical OpenGraph / Store Microdata (authoritative main product prices)
    "meta[property='og:price:amount']",
    "meta[property='product:price:amount']",
    "[itemprop='price']",
    # 3. Amazon & Kapruka Leaf Selectors (clean single-amount text)
    ".a-price .a-offscreen",
    "span.a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#pricelbl",
    ".priceM",
    # 4. WooCommerce Main Product Price Elements
    ".entry-summary .price",
    ".summary .price",
    "p.price",
    ".woocommerce-Price-amount",
    # 4. Ikman & Saltside Classifieds Leaf Elements
    "div[class*='amount--']",
    "div[class*='price-section--']",
    "span[class*='amount--']",
    # 5. Standard E-Commerce Leaf Selectors
    ".price_color",
    ".product-price",
    "span.price-item--sale",
    "span.price-item",
    "span.money",
    # 6. Marketplaces
    ".x-price-primary",
    "div[data-testid='x-price-primary']",
    ".x-bin-price__content",
    ".m-price",
    ".pdp-price",
]


def parse_price(text: str) -> Optional[float]:
    """
    Extract a numeric price float from raw scraped text.
    Handles currency symbols, thousand separators, and formatting.
    Uses regex cleaning re.sub(r"[^\\d.]", "", text).
    """
    if not text or not isinstance(text, str):
        return None

    candidate = text.strip()

    # Discount percentages or offer tags are not prices (e.g. "35%", "20% off", "-15%")
    if "%" in candidate:
        return None

    # Units of time, reading time, or non-price labels (e.g. "1 minute", "3 reviews", "5 stars")
    if any(unit in candidate.lower() for unit in ["min", "hour", "day", "month", "sec", "read", "review", "star", "sold"]):
        return None

    # Remove dots not preceded by a digit (e.g. currency abbreviation dots like "Rs.", "Rp.")
    candidate = re.sub(r"(?<!\d)\.", "", candidate)

    # Handle European decimal comma (e.g., "49,99 €" or "12,50") if followed by exactly 2 decimals
    candidate = re.sub(r",(\d{2})(?!\d)", r".\1", candidate)

    # Remove all characters except digits and decimal dots
    cleaned = re.sub(r"[^\d.]", "", candidate)
    if not cleaned:
        return None

    # If multiple dots exist (e.g. 1.299.99), preserve only the final one as decimal
    if cleaned.count(".") > 1:
        int_part, dec_part = cleaned.rsplit(".", 1)
        cleaned = int_part.replace(".", "") + "." + dec_part

    try:
        price = float(cleaned)
        return round(price, 2) if price >= 0 else None
    except ValueError:
        return None


def extract_product_title(soup: BeautifulSoup) -> str:
    """Auto-detect product title from OpenGraph, Twitter card, h1, or title tag."""
    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    tw_title = soup.select_one("meta[name='twitter:title']")
    if tw_title and tw_title.get("content"):
        return tw_title["content"].strip()

    h1 = soup.select_one("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    title = soup.select_one("title")
    if title and title.get_text(strip=True):
        raw = title.get_text(strip=True)
        for sep in [" | ", " - ", " : ", " • "]:
            if sep in raw:
                raw = raw.split(sep)[0]
        return raw.strip()

    return "Tracked Product"


def extract_price_and_selector(
    soup: BeautifulSoup,
    preferred_selector: Optional[str] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Find price and the selector that matched it.
    Checks preferred selector first, then common auto-selectors, then JSON-LD.
    """
    # 1. Try preferred selector if given and not auto
    if preferred_selector and preferred_selector.strip().lower() != "auto":
        element = soup.select_one(preferred_selector)
        if element:
            raw_text = element.get("content") or element.get_text(separator=" ", strip=True)
            price = parse_price(raw_text)
            if price is not None:
                return price, preferred_selector

    # 2. Try list of known automatic selectors
    for sel in AUTO_PRICE_SELECTORS:
        for element in soup.select(sel):
            cls = " ".join(element.get("class", []))
            if any(term in cls.lower() for term in ["discount", "percent", "badge", "saving"]):
                continue
            raw_text = element.get("content") or element.get_text(separator=" ", strip=True)
            price = parse_price(raw_text)
            if price is not None:
                return price, sel

    # 3. Try schema.org JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0] if data else {}
            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            raw_price = offers.get("price") or offers.get("lowPrice")
            if raw_price:
                price = parse_price(str(raw_price))
                if price is not None:
                    return price, "auto:json-ld"
        except Exception:
            continue

    # 4. Embedded regex patterns for dynamic stores
    raw_html = str(soup)
    patterns = [
        (r'["\']pdt_price["\']\s*:\s*["\']([^"\']+)["\']', "auto:pdt_price"),
        (r'["\']salePrice["\']\s*:\s*["\']?([\d.,]+)["\']?', "auto:salePrice"),
    ]
    for pattern, label in patterns:
        match = re.search(pattern, raw_html)
        if match:
            price = parse_price(match.group(1))
            if price is not None:
                return price, label

    # 5. Dynamic DOM scanner for elements with price/amount in class attribute
    for el in soup.find_all(["div", "span", "p", "strong", "b", "h1", "h2", "h3"], class_=True):
        classes = " ".join(el.get("class", []))
        if any(term in classes.lower() for term in ["discount", "percent", "badge", "saving"]):
            continue
        if any(term in classes.lower() for term in ["price", "amount", "cost"]):
            txt = el.get_text(separator=" ", strip=True)
            if len(txt) <= 50 and re.search(r"\d", txt):
                price = parse_price(txt)
                if price is not None and price > 0:
                    matched_cls = el.get("class", ["price"])[0]
                    return price, f"{el.name}.{matched_cls}"

    return None, None


def is_bot_challenge(html: str) -> bool:
    """Detect whether a 200 OK response is actually an anti-bot challenge interstitial."""
    if not html:
        return False
    lowered = html.lower()
    indicators = [
        "bixi.alicdn.com/punish",
        "rgv587_flag",
        'action": "deny"',
        "pardon our interruption",
        "cf-chl-bypass",
        "just a moment...",
        "error page | ebay",
    ]
    return any(ind in lowered for ind in indicators)


def get_request_cookies(url: str) -> dict:
    """Supply localization cookies so regional prices are reliably returned."""
    u = url.lower()
    cookies = {}
    if "kapruka.com" in u:
        cookies["currency"] = "LKR"
        cookies["KAP_CURRENCY"] = "LKR"
        cookies["siteCurrency"] = "LKR"
        cookies["country"] = "LK"
        cookies["selectedCurrency"] = "LKR"
    return cookies


def detect_currency(soup: BeautifulSoup, raw_price_text: str = "", url: str = "") -> str:
    """
    Detect the site's natural currency symbol based on:
    1. Schema.org / OpenGraph currency meta tags.
    2. Raw price string symbols ($, £, €, ₹, ¥, LKR, Rs).
    3. Prominent price elements on the page.
    4. Top-level domain and site context fallback.
    """
    # 1. Meta tag inspection
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        if any(k in prop for k in ["price:currency", "pricecurrency", "og:price:currency"]):
            content = (meta.get("content") or "").strip().upper()
            if content == "USD":
                return "$"
            if content == "GBP":
                return "£"
            if content == "EUR":
                return "€"
            if content == "LKR":
                return "Rs. "
            if content == "INR":
                return "₹"
            if content == "JPY":
                return "¥"
            if content:
                return f"{content} "

    # 2. Raw matched price text symbols
    txt = (raw_price_text or "").strip()
    if txt:
        if "$" in txt:
            return "$"
        if "£" in txt:
            return "£"
        if "€" in txt:
            return "€"
        if "₹" in txt:
            return "₹"
        if "¥" in txt:
            return "¥"
        if "lkr" in txt.lower() or "rs" in txt.lower():
            return "Rs. "

    # 3. Scan top price elements for currency indicators
    for sel in [".price", ".sell-price", ".a-price", ".product-price", "[class*='price']"]:
        for el in soup.select(sel)[:4]:
            t = el.get_text()
            if "$" in t:
                return "$"
            if "£" in t:
                return "£"
            if "€" in t:
                return "€"
            if "lkr" in t.lower() or "rs" in t.lower():
                return "Rs. "

    # 4. Contextual fallback based on domain
    u = url.lower()
    if ".lk" in u or "ikman" in u or "kapruka" in u or "daraz" in u:
        return "Rs. "
    if ".uk" in u or "toscrape" in u:
        return "£"
    if "amazon.com" in u or "ebay.com" in u:
        return "$"
    if ".in" in u:
        return "₹"
    if any(eu in u for eu in [".de", ".fr", ".it", ".es"]):
        return "€"

    return "Rs. "


def fetch_html_content(url: str, timeout: float = 15.0) -> Tuple[Optional[str], Optional[int]]:
    """
    Fetch webpage HTML using httpx, with automatic fallback to curl_cffi for bot-protected sites.
    """
    status_code = None
    cookies = get_request_cookies(url)

    # Attempt 1: Standard httpx client
    try:
        with httpx.Client(
            headers=DEFAULT_HEADERS,
            cookies=cookies,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                if is_bot_challenge(resp.text):
                    logger.warning("Stealth anti-bot challenge detected for %s", url)
                    status_code = 403
                else:
                    return resp.text, 200
            else:
                status_code = resp.status_code
    except Exception as exc:
        logger.warning("httpx request failed for %s: %s", url, str(exc))
        status_code = None

    # Attempt 2: curl_cffi browser TLS impersonation if available and needed (e.g. 403 Akamai/Cloudflare)
    if HAS_CURL_CFFI:
        try:
            logger.info("Attempting curl_cffi browser impersonation for %s", url)
            cffi_resp = cffi_requests.get(
                url,
                headers=DEFAULT_HEADERS,
                cookies=cookies,
                impersonate="chrome124",
                timeout=timeout,
            )
            if cffi_resp.status_code == 200:
                if is_bot_challenge(cffi_resp.text):
                    logger.warning("curl_cffi also encountered stealth anti-bot challenge for %s", url)
                    status_code = 403
                else:
                    return cffi_resp.text, 200
            else:
                status_code = cffi_resp.status_code
        except Exception as exc:
            logger.warning("curl_cffi request failed for %s: %s", url, str(exc))

    return None, status_code


def fetch_product_price(
    url: str,
    css_selector: str = "auto",
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    timeout: float = 15.0,
) -> Optional[float]:
    """
    Fetch and parse a product's price from a webpage using httpx and BeautifulSoup4.
    Includes realistic browser headers, 3 retries with exponential backoff,
    and regex price cleaning.
    """
    for attempt in range(max_retries):
        html, status_code = fetch_html_content(url, timeout=timeout)
        if html:
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")

            price, _ = extract_price_and_selector(soup, preferred_selector=css_selector)
            if price is not None:
                return price

            logger.warning(
                "Attempt %d/%d: Selector '%s' not matched on %s",
                attempt + 1,
                max_retries,
                css_selector,
                url,
            )

        if attempt < max_retries - 1:
            sleep_time = backoff_factor * (2**attempt)
            time.sleep(sleep_time)

    logger.error("Failed to fetch price for %s after %d retries", url, max_retries)
    return None


def inspect_product_page(
    url: str,
    css_selector: Optional[str] = None,
    timeout: float = 15.0,
) -> dict:
    """
    Inspect a product page from a URL alone.
    Auto-detects product title, price, and selector.
    """
    html, status_code = fetch_html_content(url, timeout=timeout)
    if not html:
        msg = f"HTTP Error {status_code}" if status_code else "Could not reach store URL"
        if status_code == 403:
            msg = "Store blocked automated request (Anti-Bot / 403 Forbidden). You can still save this item and track it."
        return {
            "success": False,
            "name": "Unknown Product",
            "price": None,
            "selector": css_selector or "auto",
            "message": msg,
        }

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title = extract_product_title(soup)
    price, matched_selector = extract_price_and_selector(soup, preferred_selector=css_selector)
    currency = detect_currency(soup, url=url)

    if price is not None:
        return {
            "success": True,
            "name": title,
            "price": price,
            "currency": currency,
            "selector": matched_selector,
            "message": f"Successfully detected price: {currency}{price:,.2f}",
        }

    return {
        "success": False,
        "name": title,
        "price": None,
        "currency": currency,
        "selector": css_selector or "auto",
        "message": "Page loaded, but could not automatically detect price element.",
    }
