"""Fill in the actual exit result for today's paper trade.

Usage after close:
    python -m backend.log_result --exit 22150          # filled at 22150
    python -m backend.log_result --exit 22150 --notes "止損出場，跳空開低"
    python -m backend.log_result --show                # print running stats
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from backend.env_guard import require
require("pandas")

import pandas as pd

PAPER_LOG = Path(__file__).resolve().parent.parent / "data" / "paper_log.csv"


def _load() -> pd.DataFrame:
    if not PAPER_LOG.exists():
        print("paper_log.csv 不存在，先執行 python -m backend.daily_signal --log")
        sys.exit(1)
    return pd.read_csv(PAPER_LOG)


def fill_result(exit_px: float, notes: str) -> None:
    df = _load()
    today = date.today().isoformat()
    mask = df["date"] == today

    if not mask.any():
        print(f"找不到今天 ({today}) 的記錄，先執行 python -m backend.daily_signal --log")
        sys.exit(1)

    idx = df[mask].index[-1]
    direction = df.at[idx, "direction"]
    entry_px  = float(df.at[idx, "entry"]) if str(df.at[idx, "entry"]).strip() else None

    if direction == "skip":
        print(f"今天是 SKIP 日，不需要填結果")
        sys.exit(0)

    if entry_px is None:
        print("進場價格欄位為空，無法計算損益")
        sys.exit(1)

    sign = 1 if direction == "long" else -1
    pnl = sign * (exit_px - entry_px)

    df.at[idx, "actual_exit"] = exit_px
    df.at[idx, "actual_pnl"]  = round(pnl, 1)
    if notes:
        df.at[idx, "notes"] = notes

    df.to_csv(PAPER_LOG, index=False)
    emoji = "✓" if pnl > 0 else "✗"
    print(f"{emoji} 今日結果記錄完成：進場={entry_px:.0f}  出場={exit_px:.0f}  損益={pnl:+.1f} pts")
    _print_stats(df)


def _print_stats(df: pd.DataFrame) -> None:
    done = df[df["actual_pnl"].notna() & (df["actual_pnl"] != "")].copy()
    if done.empty:
        print("（尚無已結算紀錄）")
        return

    done["actual_pnl"] = pd.to_numeric(done["actual_pnl"], errors="coerce")
    done = done.dropna(subset=["actual_pnl"])

    pnls  = done["actual_pnl"].tolist()
    wins  = [p for p in pnls if p > 0]
    losses= [p for p in pnls if p <= 0]
    total = sum(pnls)

    # drawdown
    cumulative = []
    running = 0.0
    for p in pnls:
        running += p
        cumulative.append(running)
    peak = cumulative[0]
    max_dd = 0.0
    for c in cumulative:
        if c > peak:
            peak = c
        dd = peak - c
        if dd > max_dd:
            max_dd = dd

    # current streak
    cur_streak = 0
    for p in reversed(pnls):
        if p <= 0:
            cur_streak += 1
        else:
            break

    print()
    print("━━━ 紙上模擬累計統計 ━━━")
    print(f"已交易天數  : {len(pnls)}")
    win_r = len(wins) / len(pnls) * 100 if pnls else 0
    print(f"勝率        : {win_r:.1f}%  ({len(wins)}勝 / {len(losses)}敗)")
    print(f"累計損益    : {total:+.1f} pts  ({total * 200 / 1000:.1f}k NTD 微台)")
    print(f"最大回落    : -{max_dd:.1f} pts")
    if cur_streak > 0:
        print(f"當前連敗    : {cur_streak} 連敗  ⚠️" if cur_streak >= 3 else f"當前連敗    : {cur_streak}")
    else:
        print(f"當前連敗    : 0")
    print("━━━━━━━━━━━━━━━━━━━━━━━━")


def show_stats() -> None:
    df = _load()
    _print_stats(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record paper trade exit result")
    parser.add_argument("--exit",  type=float, help="Actual exit price")
    parser.add_argument("--notes", default="",  help="Optional notes")
    parser.add_argument("--show",  action="store_true", help="Print running stats")
    args = parser.parse_args()

    if args.show:
        show_stats()
        return 0

    if args.exit is None:
        parser.print_help()
        return 1

    fill_result(args.exit, args.notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
