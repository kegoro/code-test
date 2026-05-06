"""
手動補發今日 ABC 選股報告。
用法：python scripts/send_report_now.py

會執行：
  1. 從資料庫計算訊號（等同 analyze_job）
  2. 透過 Telegram 推播報告（等同 notify_job）
"""
import sys, asyncio
sys.path.insert(0, ".")

from loguru import logger
from scheduler.calendar import prev_trading_date
from notifier.report import load_signals, save_signals
from notifier.telegram_notifier import send_daily_report


async def main() -> None:
    trading_date = prev_trading_date().isoformat()
    logger.info(f"[send_report_now] 交易日：{trading_date}")

    # 嘗試從已有的 signals 檔案載入
    signals = load_signals(trading_date)

    if not signals:
        logger.info("[send_report_now] 尚無 signals 檔案，從資料庫重新分析中…")
        from scheduler.daily_job import _do_analyze
        await _do_analyze()
        signals = load_signals(trading_date)

    if not signals:
        logger.error("[send_report_now] 分析完成但 signals 仍為空，請確認 DB 是否有資料")
        return

    logger.info(f"[send_report_now] 共 {len(signals)} 筆訊號，推播中…")
    await send_daily_report(signals)
    logger.info("[send_report_now] 推播完成")


if __name__ == "__main__":
    asyncio.run(main())
