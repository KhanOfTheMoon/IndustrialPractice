from urllib.parse import quote_plus

import httpx

from app.scraper.result import ScrapeResult
from app.services.category_detector import resolve_category
from app.services.category_config import get_satu_category_id, get_search_prefix
from app.services.cleaner import (
    build_query_variants,
    detect_service_query,
    is_relevant_product,
    remove_duplicates,
)
from app.services.cross_category_filter import is_wrong_category_product


BASE_URL = "https://satu.kz"
GRAPHQL_URL = "https://satu.kz/graphql"

LIMIT_PER_PAGE = 58


SEARCH_LISTING_QUERY = """
query SearchListingQuery(
  $search_term: String!,
  $offset: Int,
  $limit: Int,
  $params: Any,
  $regionId: Int = null,
  $includePremiumAdvBlock: Boolean = false
) {
  listing: searchListing(
    search_term: $search_term
    limit: $limit
    offset: $offset
    params: $params
    region: {id: $regionId}
  ) {
    searchTerm
    page {
      total
      products {
        product_item_id
        product {
          id
          name: nameForCatalog
          urlText

          image(width: 400, height: 400)
          imageAlt: image(width: 640, height: 640)

          price
          discountedPrice
          priceCurrencyLocalized
          noPriceText
          canShowPrice

          company_id
          categoryId
          categoryIds
          isService

          presence {
            presence
            isAvailable
          }

          productOpinionCounters {
            rating
            count
          }

          company {
            id
            name
            slug
            regionName
            opinionStats {
              opinionPositivePercent
              opinionTotal
            }
          }
        }
      }
    }
  }
}
"""


def build_search_query(query: str, category: str) -> str:
    """
    Добавляет поисковый префикс категории, если он задан
    """
    prefix = get_search_prefix(category)
    query_lower = query.lower()

    if prefix and prefix not in query_lower:
        return f"{prefix} {query}"

    return query


def get_product_price(product: dict) -> float | None:
    """
    Берём discountedPrice, если есть, иначе обычную price
    """
    price = product.get("discountedPrice") or product.get("price")

    if price is None:
        return None

    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def build_product_url(product: dict) -> str:

    product_id = product.get("id")
    url_text = product.get("urlText")

    if not product_id:
        return BASE_URL

    if not url_text:
        return f"{BASE_URL}/p{product_id}.html"

    if url_text.startswith("http://") or url_text.startswith("https://"):
        return url_text

    url_text = str(url_text).strip()
    url_text = url_text.replace(".html", "")
    url_text = url_text.lstrip("/")

    if url_text.startswith(f"p{product_id}-"):
        return f"{BASE_URL}/{url_text}.html"

    if url_text.startswith("p") and "-" in url_text:
        return f"{BASE_URL}/{url_text}.html"

    return f"{BASE_URL}/p{product_id}-{url_text}.html"


def build_image_url(product: dict) -> str | None:
    """
    Собирает ссылку на картинку товара
    """
    image_url = product.get("imageAlt") or product.get("image")

    if not image_url:
        return None

    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    if image_url.startswith("//"):
        return "https:" + image_url

    if image_url.startswith("/"):
        return BASE_URL + image_url

    return image_url


def parse_product_item(
    item: dict,
    query: str,
    category: str,
    source_page: int,
    strict_title_match: bool,
    include_services: bool = False,
) -> dict | None:
    product = item.get("product")

    if not product:
        return None

    title = product.get("name")

    if not title:
        return None

    price = get_product_price(product)

    if price is None:
        return None

    is_service = bool(product.get("isService"))

    if is_service and not include_services:
        return None

    if is_wrong_category_product(title, category) and not include_services:
        return None

    if not is_relevant_product(
        title=title,
        query=query,
        category=category,
        strict_title_match=strict_title_match,
    ):
        return None

    company = product.get("company") or {}
    opinion_counters = product.get("productOpinionCounters") or {}
    presence = product.get("presence") or {}

    product_url = build_product_url(product)
    image_url = build_image_url(product)

    return {
        "title": title.strip(),
        "price": price,
        "url": product_url,
        "image_url": image_url,

        "supplier": company.get("name"),
        "supplier_id": company.get("id") or product.get("company_id"),

        "product_id": product.get("id"),
        "rating": opinion_counters.get("rating"),
        "reviews_count": opinion_counters.get("count"),

        "available": bool(presence.get("isAvailable")),
        "source_page": source_page,
        "category": category,

        "company_region": company.get("regionName"),
        "company_slug": company.get("slug"),
        "company_positive_percent": (
            (company.get("opinionStats") or {}).get("opinionPositivePercent")
        ),
        "company_opinion_total": (
            (company.get("opinionStats") or {}).get("opinionTotal")
        ),
    }


async def fetch_graphql_page(
    client: httpx.AsyncClient,
    search_query: str,
    page_number: int,
    category: str,
) -> dict:
    offset = (page_number - 1) * LIMIT_PER_PAGE

    params = {
        "binary_filters": []
    }

    satu_category_id = get_satu_category_id(category)

    if satu_category_id:
        params["category"] = str(satu_category_id)

    payload = {
        "operationName": "SearchListingQuery",
        "variables": {
            "regionId": None,
            "includePremiumAdvBlock": False,
            "search_term": search_query,
            "params": params,
            "limit": LIMIT_PER_PAGE,
            "offset": offset,
        },
        "query": SEARCH_LISTING_QUERY,
    }

    response = await client.post(GRAPHQL_URL, json=payload)
    response.raise_for_status()

    return response.json()


async def scrape_products(
    query: str,
    start_page: int = 1,
    end_page: int = 1,
    strict_title_match: bool = False,
    selected_category: str = "auto",
) -> list[dict]:
    original_query = query
    category = resolve_category(original_query, selected_category)
    query_variants = build_query_variants(original_query)
    include_services = detect_service_query(original_query)

    metadata = {
        "original_query": original_query,
        "used_search_query": None,
        "query_variants": query_variants,
        "include_services": include_services,
        "message": None,
    }

    print("FAST GRAPHQL SCRAPER")
    print("RAW QUERY:", repr(original_query))
    print("ORIGINAL QUERY:", original_query)
    print("QUERY VARIANTS:", query_variants)
    print("SELECTED CATEGORY:", selected_category)
    print("RESOLVED CATEGORY:", category)
    print("INCLUDE SERVICES:", include_services)
    print("PAGE RANGE:", start_page, "-", end_page)
    print("STRICT TITLE MATCH:", strict_title_match)

    products = []

    skipped_no_price = 0
    skipped_not_relevant = 0
    skipped_service = 0
    skipped_wrong_category = 0

    headers = {
        "accept": "*/*",
        "accept-language": "ru,en;q=0.9",
        "content-type": "application/json",
        "x-apollo-operation-name": "SearchListingQuery",
        "x-apollo-operation-type": "query",
        "x-language": "ru",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "referer": BASE_URL,
        "origin": BASE_URL,
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=30,
            follow_redirects=True,
        ) as client:
            for variant_index, query_variant in enumerate(query_variants):
                search_query = build_search_query(query_variant, category)
                metadata["used_search_query"] = search_query
                client.headers["referer"] = (
                    f"{BASE_URL}/search?search_term={quote_plus(search_query)}"
                )

                print("TRYING QUERY VARIANT:", query_variant)
                print("USED SEARCH QUERY:", search_query)

                variant_products = []
                variant_had_items = False

                for page_number in range(start_page, end_page + 1):
                    print(f"FETCHING PAGE {page_number}")

                    data = await fetch_graphql_page(
                        client=client,
                        search_query=search_query,
                        page_number=page_number,
                        category=category,
                    )

                    if "errors" in data:
                        print("GRAPHQL ERRORS:", data["errors"])
                        break

                    listing = data.get("data", {}).get("listing", {})
                    page = listing.get("page", {})
                    items = page.get("products") or []

                    print(f"PAGE {page_number} ITEMS:", len(items))

                    if (
                        variant_index == 0
                        and page_number == start_page
                        and not items
                        and len(query_variants) > 1
                    ):
                        print(
                            "PAGE 1 ITEMS: 0 for original query; "
                            "trying fallback query variants"
                        )

                    if not items:
                        break

                    variant_had_items = True
                    products_before_page = len(variant_products)

                    for item in items:
                        product = item.get("product") or {}
                        title = product.get("name") or ""
                        is_service = bool(product.get("isService"))

                        if is_service and not include_services:
                            skipped_service += 1
                            continue

                        if get_product_price(product) is None:
                            skipped_no_price += 1
                            continue

                        if is_wrong_category_product(title, category) and not include_services:
                            skipped_wrong_category += 1
                            continue

                        parsed_product = parse_product_item(
                            item=item,
                            query=query_variant,
                            category=category,
                            source_page=page_number,
                            strict_title_match=strict_title_match,
                            include_services=include_services,
                        )

                        if not parsed_product:
                            skipped_not_relevant += 1
                            continue

                        variant_products.append(parsed_product)

                    products_after_page = len(variant_products)

                    if products_after_page == products_before_page:
                        print(f"PAGE {page_number}: no relevant products added")

                if variant_products:
                    products = variant_products
                    print("USING QUERY VARIANT:", query_variant)
                    print("USED SEARCH QUERY:", search_query)
                    break

                if variant_had_items:
                    print("QUERY VARIANT HAD ITEMS BUT NO RELEVANT PRODUCTS:", query_variant)
                else:
                    print("QUERY VARIANT RETURNED 0 ITEMS:", query_variant)

    except Exception as error:
        print("GraphQL scraping error:", error)
        return ScrapeResult([], metadata)

    products = remove_duplicates(products)

    if not products:
        metadata["message"] = (
            "No products found. Query was automatically simplified but still returned no results."
        )
        print(metadata["message"])

    print("SKIPPED SERVICE:", skipped_service)
    print("SKIPPED NO PRICE:", skipped_no_price)
    print("SKIPPED WRONG CATEGORY:", skipped_wrong_category)
    print("SKIPPED NOT RELEVANT:", skipped_not_relevant)
    print("FINAL PRODUCTS:", len(products))

    return ScrapeResult(products, metadata)
