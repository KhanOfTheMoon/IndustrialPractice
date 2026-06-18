import asyncio

from app.scraper.result import ScrapeResult
from app.scraper.satu_scraper import scrape_products as scrape_satu_products
from app.scraper.dns_scraper import scrape_products as scrape_dns_products


async def scrape_products(
    query: str,
    start_page: int = 1,
    end_page: int = 1,
    strict_title_match: bool = False,
    selected_category: str = "auto",
    selected_source: str = "all",
) -> list[dict]:
    tasks = []

    if selected_source in ["all", "satu"]:
        tasks.append(
            scrape_satu_products(
                query=query,
                start_page=start_page,
                end_page=end_page,
                strict_title_match=strict_title_match,
                selected_category=selected_category,
            )
        )

    if selected_source in ["all", "dns"]:
        tasks.append(
            scrape_dns_products(
                query=query,
                start_page=start_page,
                end_page=end_page,
                strict_title_match=strict_title_match,
                selected_category=selected_category,
            )
        )

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    products = []
    metadata = {}

    for result in results:
        if isinstance(result, Exception):
            print("SCRAPER ERROR:", result)
            continue

        result_metadata = getattr(result, "metadata", None)

        if result_metadata:
            metadata.update(result_metadata)

        products.extend(result)

    return ScrapeResult(products, metadata)
