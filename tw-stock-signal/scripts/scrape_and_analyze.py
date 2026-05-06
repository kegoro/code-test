"""
Scrape Vocus + Threads content, then generate strategy analysis.

Usage:
  python scripts/scrape_and_analyze.py            # full pipeline
  python scripts/scrape_and_analyze.py --vocus    # Vocus only
  python scripts/scrape_and_analyze.py --threads  # Threads only
  python scripts/scrape_and_analyze.py --analyze  # analyze already-scraped docs (skip scraping)
"""
import sys
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from scrapers.content_scraper import VocusScraper, ThreadsScraper

logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")


async def run_scraping(vocus: bool, threads: bool) -> None:
    if vocus:
        logger.info("━━ Scraping Vocus ━━")
        scraper = VocusScraper()
        articles = await scraper.scrape_all()
        logger.info(f"[vocus] Done: {len(articles)} articles saved to docs/vocus/")
        paid = sum(1 for a in articles if a.is_paid)
        if paid:
            logger.warning(f"[vocus] {paid} paid articles (content truncated)")

    if threads:
        logger.info("━━ Scraping Threads ━━")
        scraper = ThreadsScraper()
        posts = await scraper.scrape_all()
        logger.info(f"[threads] Done: {len(posts)} posts saved to docs/threads/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocus",   action="store_true")
    parser.add_argument("--threads", action="store_true")
    parser.add_argument("--analyze", action="store_true",
                        help="Skip scraping, only re-run analysis on existing docs/")
    args = parser.parse_args()

    run_vocus   = args.vocus   or (not args.threads and not args.analyze)
    run_threads = args.threads or (not args.vocus   and not args.analyze)

    if not args.analyze:
        asyncio.run(run_scraping(run_vocus, run_threads))
    else:
        logger.info("[analyze] Using existing scraped docs — skipping scraping")

    logger.info("Scraping complete. Run the strategy analysis step next.")
    logger.info("  → docs/vocus/     (Vocus articles)")
    logger.info("  → docs/threads/   (Threads posts)")
    logger.info("  → docs/failed_urls.txt (any failures)")


if __name__ == "__main__":
    main()
