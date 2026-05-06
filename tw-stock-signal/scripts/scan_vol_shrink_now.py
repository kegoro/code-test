"""
即時執行全市場「連續五日量縮不破低」掃描，完成後推播 Telegram。
用法：python scripts/scan_vol_shrink_now.py
"""
import sys, asyncio
sys.path.insert(0, ".")

from datetime import date
from loguru import logger

from scrapers.twse.ticker_list import fetch_full_ticker_list
from strategy.volume_shrink import scan_stocks, save_result_csv, format_result
from notifier.report import build_vol_shrink_message
from notifier.telegram_notifier import send_html_message


async def main() -> None:
    trading_date = date.today().isoformat()

    # 1. 取全市場清單（有快取則直接用）
    tickers = await fetch_full_ticker_list()
    if not tickers:
        logger.error("無法取得股票清單，請確認網路連線")
        return

    twse_n = sum(1 for t in tickers if t["market"] == "twse")
    otc_n  = sum(1 for t in tickers if t["market"] == "otc")
    logger.info(f"掃描清單：上市 {twse_n} + 上櫃 {otc_n} = {len(tickers)} 支")

    # 2. 掃描（在 executor 內執行，保持事件迴圈順暢）
    loop = asyncio.get_running_loop()
    matches = await loop.run_in_executor(
        None,
        lambda: scan_stocks(
            tickers, consecutive=5, threshold=0.10,
            max_workers=8, min_avg_volume_lots=2000,
        ),
    )

    # 3. 儲存 CSV
    if matches:
        csv_path = save_result_csv(matches, trading_date)
        logger.info(f"{len(matches)} 支符合 → {csv_path}")
        print(format_result(matches))
    else:
        logger.info("本次掃描無符合標的")

    # 4. 推播 Telegram（不管有沒有符合都推）
    msgs = build_vol_shrink_message(matches, trading_date)
    for msg in msgs:
        await send_html_message(msg)
    logger.info(f"Telegram 推播完成（{len(msgs)} 則）")


if __name__ == "__main__":
    asyncio.run(main())
