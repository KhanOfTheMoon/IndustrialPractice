import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin

import httpx

from app.scraper.result import ScrapeResult
from app.services.cleaner import is_relevant_product


BASE_URL = "https://www.dns-shop.kz"
SEARCH_URL = f"{BASE_URL}/search/"
PRODUCT_BUY_URL = f"{BASE_URL}/ajax-state/product-buy/"
DNS_BLOCKED_MESSAGE = (
    "DNS is currently unavailable because dns-shop.kz blocks server-side requests."
)


def build_blocked_result() -> ScrapeResult:
    return ScrapeResult(
        [],
        {
            "dns_blocked": True,
            "message": DNS_BLOCKED_MESSAGE,
        },
    )


def is_dns_blocked_response(status_code: int, html: str) -> bool:
    if status_code in {403, 429}:
        return True

    lower_html = html.lower()

    blocked_markers = [
        "captcha",
        "cloudflare",
        "forbidden",
        "access denied",
        "enable javascript and cookies",
        "robot",
        "blocked",
    ]

    return any(marker in lower_html for marker in blocked_markers)


def is_unexpected_dns_html(html: str) -> bool:
    lower_html = html.lower()

    expected_markers = [
        "catalog-product",
        "/product/",
        "product-buy",
        "search",
    ]

    if any(marker in lower_html for marker in expected_markers):
        return False

    return True


class DnsCardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.current_card = None
        self.depth = 0
        self.capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {
            name.lower(): value or ""
            for name, value in attrs
        }
        class_name = attrs_dict.get("class", "")

        starts_card = (
            self.current_card is None
            and "catalog-product" in class_name.split()
        )

        if starts_card:
            self.current_card = {
                "title_parts": [],
                "url": None,
                "image_url": None,
                "product_id": None,
                "container_id": None,
            }
            self.depth = 1
        elif self.current_card is not None and tag not in {"br", "img", "input", "meta", "link"}:
            self.depth += 1

        if self.current_card is None:
            return

        self._collect_ids(attrs_dict)

        href = attrs_dict.get("href")
        if tag == "a" and href and "/product/" in href:
            self.current_card["url"] = urljoin(BASE_URL, href)
            self.capture_title = True

        if tag == "img":
            image_url = (
                attrs_dict.get("data-src")
                or attrs_dict.get("src")
                or attrs_dict.get("data-original")
            )

            if image_url and not self.current_card["image_url"]:
                self.current_card["image_url"] = normalize_url(image_url)

        if tag == "source":
            srcset = attrs_dict.get("data-srcset") or attrs_dict.get("srcset")

            if srcset and not self.current_card["image_url"]:
                self.current_card["image_url"] = normalize_url(srcset.split()[0])

    def handle_data(self, data: str) -> None:
        if self.current_card is not None and self.capture_title:
            title = data.strip()

            if title:
                self.current_card["title_parts"].append(title)

    def handle_endtag(self, tag: str) -> None:
        if self.current_card is None:
            return

        if tag == "a":
            self.capture_title = False

        self.depth -= 1

        if self.depth <= 0:
            title = " ".join(self.current_card["title_parts"]).strip()

            if title and self.current_card["url"]:
                self.cards.append({
                    "title": normalize_whitespace(title),
                    "url": self.current_card["url"],
                    "image_url": self.current_card["image_url"],
                    "product_id": self.current_card["product_id"],
                    "container_id": self.current_card["container_id"],
                })

            self.current_card = None
            self.capture_title = False
            self.depth = 0

    def _collect_ids(self, attrs: dict[str, str]) -> None:
        product_id = (
            attrs.get("data-product-id")
            or attrs.get("data-product")
            or attrs.get("data-code")
            or attrs.get("data-id")
        )

        if product_id and not self.current_card["product_id"]:
            self.current_card["product_id"] = product_id

        container_id = (
            attrs.get("data-container-id")
            or attrs.get("data-state-id")
            or attrs.get("data-state")
        )
        element_id = attrs.get("id", "")
        class_name = attrs.get("class", "")

        if not container_id and "product-buy" in element_id:
            container_id = element_id

        if not container_id and "product-buy" in class_name:
            container_id = attrs.get("data-id") or attrs.get("id")

        if container_id and not self.current_card["container_id"]:
            self.current_card["container_id"] = container_id


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):
        return "https:" + url

    return urljoin(BASE_URL, url)


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return normalize_whitespace(text)


def extract_csrf_token(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf-token["\']',
        r'<input[^>]+name=["\']_csrf["\'][^>]+value=["\']([^"\']+)["\']',
        r'csrfToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)

        if match:
            return unescape(match.group(1))

    return None


def extract_product_cards(html: str) -> list[dict]:
    cards = extract_cards_with_regex(html)

    if cards:
        return cards

    parser = DnsCardParser()
    parser.feed(html)
    return parser.cards


def extract_cards_with_regex(html: str) -> list[dict]:
    starts = [
        match.start()
        for match in re.finditer(
            r'<[^>]+class=["\']([^"\']+)["\'][^>]*>',
            html,
            flags=re.IGNORECASE,
        )
        if "catalog-product" in match.group(1).split()
    ]
    cards = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(html)
        block = html[start:end]
        card = parse_card_block(block)

        if card:
            cards.append(card)

    return cards


def parse_card_block(block: str) -> dict | None:
    link_match = re.search(
        r'<a[^>]+href=["\']([^"\']*/product/[^"\']*)["\'][^>]*>(.*?)</a>',
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not link_match:
        return None

    title = strip_tags(link_match.group(2))

    if not title:
        return None

    product_id = first_regex_group(
        block,
        [
            r'data-product-id=["\']([^"\']+)["\']',
            r'data-product=["\']([^"\']+)["\']',
            r'data-code=["\']([^"\']+)["\']',
            r'data-id=["\']([^"\']+)["\']',
        ],
    )
    container_id = first_regex_group(
        block,
        [
            r'id=["\']([^"\']*product-buy[^"\']*)["\']',
            r'data-container-id=["\']([^"\']+)["\']',
            r'data-state-id=["\']([^"\']+)["\']',
        ],
    )
    image_url = first_regex_group(
        block,
        [
            r'<img[^>]+data-src=["\']([^"\']+)["\']',
            r'<img[^>]+src=["\']([^"\']+)["\']',
            r'<source[^>]+data-srcset=["\']([^"\'\s]+)',
            r'<source[^>]+srcset=["\']([^"\'\s]+)',
        ],
    )

    return {
        "title": title,
        "url": urljoin(BASE_URL, unescape(link_match.group(1))),
        "image_url": normalize_url(unescape(image_url)) if image_url else None,
        "product_id": product_id,
        "container_id": container_id,
    }


def first_regex_group(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)

        if match:
            return unescape(match.group(1))

    return None


def build_product_buy_containers(cards: list[dict]) -> list[dict]:
    containers = []

    for card in cards:
        product_id = card.get("product_id")
        container_id = card.get("container_id")

        if not product_id or not container_id:
            continue

        containers.append({
            "id": container_id,
            "data": {
                "id": product_id,
                "product_id": product_id,
            },
        })

    return containers


def build_product_buy_payloads(cards: list[dict]) -> list[str]:
    containers = build_product_buy_containers(cards)

    if not containers:
        return []

    return [
        json.dumps(containers, ensure_ascii=False),
        json.dumps({"containers": containers}, ensure_ascii=False),
    ]


def parse_numeric_price(value) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    numbers = re.findall(r"\d+", str(value))

    if not numbers:
        return None

    return float("".join(numbers))


def extract_price_from_state(state: dict) -> float | None:
    data = state.get("data") or {}
    price = data.get("price") or {}

    if isinstance(price, dict):
        return parse_numeric_price(price.get("current"))

    return parse_numeric_price(price)


def extract_prices(response_json: dict, cards: list[dict]) -> dict[str, float]:
    response_data = response_json.get("data") or {}
    states = response_json.get("states") or response_data.get("states") or []

    if isinstance(states, dict):
        states = list(states.values())

    prices_by_container = {}
    ordered_prices = []

    for state in states:
        if not isinstance(state, dict):
            continue

        price = extract_price_from_state(state)

        if price is None:
            continue

        ordered_prices.append(price)
        state_id = (
            state.get("id")
            or state.get("containerId")
            or state.get("container_id")
        )

        if state_id:
            prices_by_container[str(state_id)] = price

    if prices_by_container:
        return prices_by_container

    for card, price in zip(cards, ordered_prices):
        container_id = card.get("container_id")

        if container_id:
            prices_by_container[str(container_id)] = price

    return prices_by_container


async def fetch_dns_prices(
    client: httpx.AsyncClient,
    cards: list[dict],
    csrf_token: str | None,
) -> dict[str, float]:
    priced_cards = [
        card for card in cards
        if card.get("product_id") and card.get("container_id")
    ]

    if not priced_cards:
        return {}

    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": BASE_URL,
        "referer": str(client.headers.get("referer", BASE_URL)),
        "x-requested-with": "XMLHttpRequest",
    }

    if csrf_token:
        headers["x-csrf-token"] = csrf_token

    for payload in build_product_buy_payloads(priced_cards):
        response = await client.post(
            PRODUCT_BUY_URL,
            data={"data": payload},
            headers=headers,
        )
        response.raise_for_status()

        prices = extract_prices(response.json(), priced_cards)

        if prices:
            return prices

    return {}


def build_search_url(query: str, page_number: int) -> str:
    page_param = f"&p={page_number}" if page_number > 1 else ""
    return f"{SEARCH_URL}?q={quote_plus(query)}{page_param}"


def build_product(card: dict, price: float, source_page: int, category: str) -> dict:
    return {
        "title": card["title"],
        "price": price,
        "url": card["url"],
        "image_url": card.get("image_url"),
        "supplier": "DNS",
        "source": "dns",
        "source_page": source_page,
        "category": category,
        "product_id": card.get("product_id"),
        "container_id": card.get("container_id"),
    }


async def scrape_products(
    query: str,
    start_page: int = 1,
    end_page: int = 1,
    strict_title_match: bool = False,
    selected_category: str = "auto",
) -> list[dict]:
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "ru,en;q=0.9",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    products = []

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=30,
            follow_redirects=True,
        ) as client:
            for page_number in range(start_page, end_page + 1):
                search_url = build_search_url(query, page_number)
                client.headers["referer"] = search_url

                try:
                    response = await client.get(search_url)
                except httpx.HTTPError:
                    print("DNS blocked server request")
                    return build_blocked_result()

                if is_dns_blocked_response(response.status_code, response.text):
                    print("DNS blocked server request")
                    return build_blocked_result()

                if response.status_code != 200:
                    print("DNS blocked server request")
                    return build_blocked_result()

                html = response.text

                if is_dns_blocked_response(200, html) or is_unexpected_dns_html(html):
                    print("DNS blocked server request")
                    return build_blocked_result()

                cards = extract_product_cards(html)

                print(f"DNS PAGE {page_number} CARDS:", len(cards))

                if not cards:
                    print("DNS blocked server request")
                    return build_blocked_result()

                csrf_token = extract_csrf_token(html)
                try:
                    prices = await fetch_dns_prices(client, cards, csrf_token)
                except httpx.HTTPError:
                    print("DNS blocked server request")
                    return build_blocked_result()

                if not prices:
                    print("DNS blocked server request")
                    return build_blocked_result()

                for card in cards:
                    price = prices.get(str(card.get("container_id")))

                    if price is None:
                        continue

                    if strict_title_match and not is_relevant_product(
                        title=card["title"],
                        query=query,
                        category="general",
                        strict_title_match=True,
                    ):
                        continue

                    products.append(
                        build_product(
                            card=card,
                            price=price,
                            source_page=page_number,
                            category=selected_category,
                        )
                    )

    except Exception:
        print("DNS blocked server request")
        return build_blocked_result()

    print("DNS FINAL PRODUCTS:", len(products))

    if not products:
        return ScrapeResult(products, {})

    return ScrapeResult(products, {})
