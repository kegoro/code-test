"""
連續五日量縮不破低 回測執行腳本

用法：
  # 全市場（約 1956 支，需 7-10 分鐘）
  python scripts/run_backtest.py

  # 快速測試（只跑 watchlist 20 支）
  python scripts/run_backtest.py --quick
"""
import sys, asyncio, argparse
sys.path.insert(0, ".")

from datetime import date
from loguru import logger

from scrapers.twse.ticker_list import fetch_full_ticker_list
from strategy.backtest_vol_shrink import run_backtest, save_backtest_csv, compute_summary
from notifier.report import build_backtest_message
from notifier.telegram_notifier import send_html_message


def _load_watchlist() -> list[dict]:
    import yaml
    from config.settings import settings
    with open(settings.watchlist_path, encoding="utf-8") as f:
        stocks = yaml.safe_load(f)["stocks"]
    # watchlist 沒有 market 欄位，預設 twse
    for s in stocks:
        s.setdefault("market", "twse")
    return stocks


async def main(quick: bool = False) -> None:
    run_date = date.today().isoformat()

    # ── 1. 取股票清單 ────────────────────────────────────────────────────────
    if quick:
        tickers = _load_watchlist()
        logger.info(f"[backtest] 快速模式：watchlist {len(tickers)} 支")
    else:
        tickers = await fetch_full_ticker_list()
        if not tickers:
            logger.error("[backtest] 無法取得股票清單，請確認網路連線")
            return
        logger.info(f"[backtest] 全市場模式：{len(tickers)} 支")

    # ── 2. 執行回測 ──────────────────────────────────────────────────────────
    logger.info("[backtest] 開始回測（yfinance 2年歷史資料）...")
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None,
        lambda: run_backtest(tickers, max_workers=8),
    )

    logger.info(f"[backtest] 共找到 {len(results)} 筆型態命中記錄")

    # ── 3. 儲存 CSV ──────────────────────────────────────────────────────────
    csv_path = save_backtest_csv(results, run_date)

    # ── 4. 計算摘要 ──────────────────────────────────────────────────────────
    summary = compute_summary(results)

    # Console 摘要
    passed = [r for r in results if r.all_pass]
    print("\n" + "="*60)
    print(f"  回測完成  {run_date}")
    print("="*60)
    print(f"  型態命中（原始）：{summary['total_patterns']:,} 次")
    print(f"  通過 A          ：{summary['pass_a']} 次")
    print(f"  通過 A+B1       ：{summary['pass_ab1']} 次")
    print(f"  通過 A+B1+B2    ：{summary['passed']} 次")

    if passed:
        print()
        print(f"  5日後平均報酬  ：{summary['avg_r5']:+.1f}%  勝率 {summary['wr5']:.0f}%")
        print(f"  10日後平均報酬 ：{summary['avg_r10']:+.1f}%  勝率 {summary['wr10']:.0f}%")
        print(f"  20日後平均報酬 ：{summary['avg_r20']:+.1f}%  勝率 {summary['wr20']:.0f}%")
        print()
        print("  歷史觸發最多：")
        for sym_name, cnt in summary["top_stocks"]:
            print(f"    {sym_name}：{cnt} 次")

        # 印出 A+B1+B2 通過的個別案例
        print("\n  通過全部條件的案例（前20筆）：")
        header = f"  {'代號':<6} {'名稱':<8} {'型態日':<12} {'收盤':>6} {'量比':>6} {'距年高':>7} {'5日%':>7} {'10日%':>7} {'20日%':>7}"
        print(header)
        print("  " + "-"*74)
        for r in passed[:20]:
            r5  = f"{r.r5:+.1f}"  if r.r5  is not None else "N/A"
            r10 = f"{r.r10:+.1f}" if r.r10 is not None else "N/A"
            r20 = f"{r.r20:+.1f}" if r.r20 is not None else "N/A"
            print(f"  {r.symbol:<6} {r.name:<8} {r.pattern_date:<12} "
                  f"{r.close_on_pattern:>6.1f} {r.vol_ratio:>6.2f} "
                  f"{r.dist_from_52w_high:>6.1f}% {r5:>7} {r10:>7} {r20:>7}")

    print(f"\n  完整結果已存至：{csv_path}")
    print("="*60)

    # ── 5. 推播 Telegram ─────────────────────────────────────────────────────
    msgs = build_backtest_message(summary, run_date, str(csv_path))
    for msg in msgs:
        await send_html_message(msg)
    logger.info(f"[backtest] Telegram 推播完成（{len(msgs)} 則）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="量縮不破低回測")
    parser.add_argument("--quick", action="store_true", help="只跑 watchlist（快速測試）")
    args = parser.parse_args()
    asyncio.run(main(quick=args.quick))
