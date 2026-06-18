import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.scraper.site_scraper import scrape_products
from app.services.analyzer import analyze_prices, analyze_suppliers
from app.services.ranker import rank_products
from app.services.outlier_filter import filter_price_outliers


app = FastAPI(title="Product Price Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "Product Price Analyzer API is running"
    }


@app.get("/analyze")
async def analyze(
    query: str = Query(..., min_length=2),
    start_page: int = Query(1, ge=1),
    end_page: int = Query(1, ge=1, le=20),
    remove_outliers: bool = Query(True),
    strict_title_match: bool = Query(False),
    best_limit: int = Query(20, ge=1, le=50),
    selected_category: str = Query("auto"),
    selected_source: str = Query("all"),
):
    if end_page < start_page:
        return {
            "error": "end_page must be greater than or equal to start_page"
        }

    allowed_sources = ["all", "satu", "dns"]

    if selected_source not in allowed_sources:
        return {
            "error": "selected_source must be one of: all, satu, dns"
        }

    products = await scrape_products(
        query=query,
        start_page=start_page,
        end_page=end_page,
        strict_title_match=strict_title_match,
        selected_category=selected_category,
        selected_source=selected_source,
    )
    scraper_metadata = getattr(products, "metadata", {}) or {}
    response_query_metadata = {
        "original_query": scraper_metadata.get("original_query", query),
        "used_search_query": scraper_metadata.get("used_search_query", query),
        "query_variants": scraper_metadata.get("query_variants", [query]),
        "include_services": scraper_metadata.get("include_services", False),
    }

    if not products:
        return {
            "query": query,
            **response_query_metadata,
            "selected_category": selected_category,
            "selected_source": selected_source,
            "start_page": start_page,
            "end_page": end_page,
            "remove_outliers": remove_outliers,
            "strict_title_match": strict_title_match,
            "best_limit": best_limit,
            "total_found": 0,
            "message": scraper_metadata.get("message") or "No relevant products found"
        }

    total_before_outlier_filter = len(products)

    if remove_outliers:
        products = filter_price_outliers(products)

    total_after_outlier_filter = len(products)
    removed_as_outliers = total_before_outlier_filter - total_after_outlier_filter

    if not products:
        return {
            "query": query,
            **response_query_metadata,
            "selected_category": selected_category,
            "selected_source": selected_source,
            "start_page": start_page,
            "end_page": end_page,
            "remove_outliers": remove_outliers,
            "strict_title_match": strict_title_match,
            "best_limit": best_limit,
            "total_found": 0,
            "total_before_outlier_filter": total_before_outlier_filter,
            "removed_as_outliers": removed_as_outliers,
            "message": "All products were removed as price outliers"
        }

    price_stats = analyze_prices(products)
    suppliers = analyze_suppliers(products)
    ranked_products = rank_products(products, price_stats)

    return {
        "query": query,
        **response_query_metadata,
        "selected_category": selected_category,
        "selected_source": selected_source,
        "start_page": start_page,
        "end_page": end_page,
        "remove_outliers": remove_outliers,
        "strict_title_match": strict_title_match,
        "best_limit": best_limit,
        "total_before_outlier_filter": total_before_outlier_filter,
        "removed_as_outliers": removed_as_outliers,
        "total_found": len(products),
        "price_stats": price_stats,
        "suppliers": suppliers,
        "best_offers": ranked_products[:best_limit],
        "all_products": ranked_products,
    }
