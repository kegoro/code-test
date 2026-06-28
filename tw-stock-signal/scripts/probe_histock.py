"""
PoC probe: hit HiStock 籌碼集中度 candidate pages once for ONE stock,
report HTTP status + content length + table tag count.

Usage:
    python scripts/probe_histock.py [stock_id]

Default stock_id = 2330. Run from repo root so config/settings.py imports cleanly.

This script intentionally:
  - Hits the live HiStock site (your real IP is recorded in their access log).
  - Probes 3 candidate URLs sequentially with 2-5s random delay between each.
  - Persists raw HTML to scripts/poc_data/histock_<stock_id>_<page>.html
    so the parser can be written from real markup, not guesses.

Run only after explicit user confirmation — do NOT loop / batch this.
"""
from __future__ import annotations
import asyncio
import random
import sys
from pathlib import Path
from typing import Final

import httpx
from bs4 import BeautifulSoup
from loguru import logger


_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_OUT_DIR: Final[Path] = _REPO_ROOT / "scripts" / "poc_data"

# Candidate pages — actual content unknown until probed.
_CANDIDATES: Final[dict[str, str]] = {
    "concentrate":      "https://histock.tw/stock/concentrate.aspx?no={sid}",
    "chips":            "https://histock.tw/stock/chips.aspx?no={sid}",
    "concentratemonth": "https://histock.tw/stock/concentratemonth.aspx?no={sid}",
}

_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

_TIMEOUT_SEC: Final[float] = 15.0


async def _probe_one(client: httpx.AsyncClient, label: str, url: str, stock_id: str) -> None:
    """Hit one candidate page and write raw HTML + summary."""
    try:
        await asyncio.sleep(random.uniform(2.0, 5.0))  # be polite
        resp = await client.get(url, headers=_HEADERS, timeout=_TIMEOUT_SEC)
        body = resp.text
        soup = BeautifulSoup(body, "lxml")
        tables = soup.find_all("table")
        title = (soup.title.text.strip() if soup.title else "<no title>")[:80]

        out_path = _OUT_DIR / f"histock_{stock_id}_{label}.html"
        out_path.write_text(body, encoding="utf-8")

        logger.info(
            f"[{label}] HTTP {resp.status_code} | "
            f"{len(body):>7,} bytes | tables={len(tables)} | "
            f"title={title!r} | saved → {out_path.relative_to(_REPO_ROOT)}"
        )
    except httpx.HTTPError as exc:
        logger.error(f"[{label}] HTTP error: {type(exc).__name__}: {exc}")
    except Exception as exc:
        logger.error(f"[{label}] Unexpected: {type(exc).__name__}: {exc}")


async def main(stock_id: str) -> None:
    """Probe all candidate pages once for the given stock_id."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Probing HiStock for {stock_id} → {_OUT_DIR}")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for label, url_tpl in _CANDIDATES.items():
            await _probe_one(client, label, url_tpl.format(sid=stock_id), stock_id)
    logger.info("Probe complete. Inspect saved HTML before writing the parser.")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    asyncio.run(main(sid))
