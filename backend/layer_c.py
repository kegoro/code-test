"""Layer C — Backtest engine: A (macro bias) + B (ORH/ORL) + C1 (US divergence).

Entry logic:
  LONG  : bias_a > 0  AND  price breaks above ORH  AND  no top-divergence (C1)
  SHORT : bias_a < 0  AND  price breaks below ORL   AND  no bot-divergence (C1)

Exit logic:
  Stop   : entry ± STOP_PTS
  Target : entry ± TARGET_PTS   (OR-range × REWARD_MULT)
  Time   : close at 13:30 bar (avoid holding into close auction)

C1 divergence (daily simplified):
  Top divergence  : on trade date D, one US index made N-day high but NOT all 3 did
  Bot divergence  : one US index made N-day low  but NOT all 3 did
  → divergence present = weaker confirmation → skip entry in that direction

Usage:
    python -m backend.layer_c                   # run backtest, print summary
    python -m backend.layer_c --trades out.csv  # also save trade log
    python -m backend.layer_c --no-c1           # disable C1 filter (benchmark)
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import pandas as pd

from backend.layer_a import DATA_PATH as LAYER_A_PATH
from backend.layer_a import load as load_layer_a
from backend.layer_b import SESSION_START, SESSION_END, compute_sessions, load_1m

logger = logging.getLogger("layer_c")

# ── parameters ────────────────────────────────────────────────────────────────
OR_WINDOW_MIN  = 30      # opening range window (minutes)
STOP_PTS       = 30      # stop loss in index points
REWARD_MULT    = 2.0     # target = OR_range × this
TIME_EXIT      = time(13, 30)   # force-close time
BIAS_THRESHOLD = 1       # |bias_a| must be >= this to trade
DIV_WINDOW     = 20      # N-day window for C1 divergence check


# ── C1 divergence ─────────────────────────────────────────────────────────────

def compute_c1_divergence(bias_df: pd.DataFrame, window: int = DIV_WINDOW) -> pd.DataFrame:
    """Add c1_top_div / c1_bot_div columns to the bias DataFrame.

    Top divergence: at least one index at N-day high but not all three.
    Bot divergence: at least one index at N-day low  but not all three.
    """
    df = bias_df.copy()
    index_cols = [c for c in ["dji", "spx", "ndx"] if c in df.columns]
    if len(index_cols) < 2:
        df["c1_top_div"] = False
        df["c1_bot_div"] = False
        return df

    roll_high = df[index_cols].rolling(window).max()
    roll_low  = df[index_cols].rolling(window).min()

    at_high = (df[index_cols] >= roll_high)
    at_low  = (df[index_cols] <= roll_low)

    any_at_high = at_high.any(axis=1)
    all_at_high = at_high.all(axis=1)
    any_at_low  = at_low.any(axis=1)
    all_at_low  = at_low.all(axis=1)

    # divergence = some but NOT all confirming
    df["c1_top_div"] = any_at_high & ~all_at_high
    df["c1_bot_div"] = any_at_low  & ~all_at_low
    return df


# ── trade dataclass ───────────────────────────────────────────────────────────

@dataclass
class Trade:
    date:       object
    direction:  str       # "long" / "short"
    entry_time: object
    entry_px:   float
    exit_time:  object
    exit_px:    float
    exit_reason: str      # "stop" / "target" / "time"
    pnl_pts:    float = field(init=False)

    def __post_init__(self):
        sign = 1 if self.direction == "long" else -1
        self.pnl_pts = sign * (self.exit_px - self.entry_px)


# ── bar-by-bar simulation (one day) ──────────────────────────────────────────

def _simulate_day(
    bars: pd.DataFrame,
    direction: str,
    entry_trigger: float,   # ORH for long, ORL for short
    stop_pts: float,
    target_pts: float,
) -> Trade | None:
    """Walk 1-min bars after OR window; return first triggered trade or None."""
    sign = 1 if direction == "long" else -1
    entered = False
    entry_time = entry_px = None

    for _, row in bars.iterrows():
        bar_time = row["datetime"].time()
        if bar_time > TIME_EXIT:
            break

        if not entered:
            # entry: price crosses trigger level
            if direction == "long"  and row["high"] >= entry_trigger:
                entry_px   = entry_trigger
                entry_time = row["datetime"]
                entered    = True
            elif direction == "short" and row["low"] <= entry_trigger:
                entry_px   = entry_trigger
                entry_time = row["datetime"]
                entered    = True
            continue

        # position management
        stop_px   = entry_px - sign * stop_pts
        target_px = entry_px + sign * target_pts

        if direction == "long":
            if row["low"] <= stop_px:
                return Trade(bars["datetime"].iloc[0].date(), direction,
                             entry_time, entry_px, row["datetime"], stop_px, "stop")
            if row["high"] >= target_px:
                return Trade(bars["datetime"].iloc[0].date(), direction,
                             entry_time, entry_px, row["datetime"], target_px, "target")
        else:
            if row["high"] >= stop_px:
                return Trade(bars["datetime"].iloc[0].date(), direction,
                             entry_time, entry_px, row["datetime"], stop_px, "stop")
            if row["low"] <= target_px:
                return Trade(bars["datetime"].iloc[0].date(), direction,
                             entry_time, entry_px, row["datetime"], target_px, "target")

    # time exit
    if entered:
        last_bar = bars[bars["datetime"].dt.time <= TIME_EXIT].iloc[-1]
        return Trade(bars["datetime"].iloc[0].date(), direction,
                     entry_time, entry_px, last_bar["datetime"], last_bar["close"], "time")
    return None


# ── main backtest ─────────────────────────────────────────────────────────────

def run_backtest(
    *,
    stop_pts:       float = STOP_PTS,
    reward_mult:    float = REWARD_MULT,
    bias_threshold: int   = BIAS_THRESHOLD,
    or_window_min:  int   = OR_WINDOW_MIN,
    div_window:     int   = DIV_WINDOW,
    use_c1:         bool  = True,
    max_or:         float = 0.0,   # 0 = no filter
    ma_window:      int   = 0,     # 0 = no filter; N = require open > MA(N) for long
) -> tuple[list[Trade], pd.DataFrame]:
    """Return (trades, sessions_df).

    sessions_df has one row per trading day with all layer outputs + trade result.
    """
    df_1m     = load_1m()
    sessions  = compute_sessions(df_1m, or_window_min=or_window_min)

    # pre-compute daily close & open for MA trend filter
    daily = (
        df_1m.groupby(df_1m["datetime"].dt.date)
        .agg(day_open=("open", "first"), day_close=("close", "last"))
        .reset_index()
        .rename(columns={"datetime": "date"})
    )
    daily["ma"] = daily["day_close"].shift(1).rolling(ma_window).mean() if ma_window > 0 else None
    daily = daily.set_index("date")

    bias_raw  = load_layer_a()
    bias_df   = compute_c1_divergence(bias_raw, window=div_window) if use_c1 else bias_raw

    # align: sessions date → bias date (bias is US close = prev TW date usually)
    # use most recent available US close before each TW trading date
    bias_df = bias_df.copy()
    bias_df.index = pd.to_datetime(bias_df.index)

    trades: list[Trade] = []
    results = []

    for _, sess in sessions.iterrows():
        tw_date = pd.Timestamp(sess["date"])

        # Layer A: most recent US close on or before this TW trading date
        prior_bias = bias_df[bias_df.index <= tw_date]
        if prior_bias.empty:
            continue
        day_bias = prior_bias.iloc[-1]
        bias_a   = int(day_bias["bias_a"])

        # C1 divergence flags from same prior US session
        c1_top = bool(day_bias.get("c1_top_div", False))
        c1_bot = bool(day_bias.get("c1_bot_div", False))

        orh = sess["orh"]
        orl = sess["orl"]
        or_range = sess["or_range_pts"]
        target_pts = max(or_range * reward_mult, stop_pts * reward_mult)

        # determine direction
        direction = None
        skip_reason = ""

        # MA trend filter: today's open vs N-day MA of previous closes
        ma_val = None
        if ma_window > 0 and sess["date"] in daily.index:
            ma_val = daily.loc[sess["date"], "ma"]
            day_open = daily.loc[sess["date"], "day_open"]

        if max_or > 0 and or_range > max_or:
            skip_reason = f"or_range={or_range:.0f}>{max_or:.0f}"
        elif bias_a >= bias_threshold:
            if use_c1 and c1_top:
                skip_reason = "c1_top_div"
            elif ma_window > 0 and ma_val is not None and not pd.isna(ma_val) and day_open <= ma_val:
                skip_reason = f"ma_trend:open({day_open:.0f})<=ma({ma_val:.0f})"
            else:
                direction = "long"
        elif bias_a <= -bias_threshold:
            if use_c1 and c1_bot:
                skip_reason = "c1_bot_div"
            elif ma_window > 0 and ma_val is not None and not pd.isna(ma_val) and day_open >= ma_val:
                skip_reason = f"ma_trend:open({day_open:.0f})>=ma({ma_val:.0f})"
            else:
                direction = "short"
        else:
            skip_reason = f"bias_a={bias_a} below threshold"

        # run simulation on post-OR bars
        trade = None
        if direction:
            day_bars = df_1m[df_1m["datetime"].dt.date == sess["date"]].copy()
            if day_bars.empty:
                skip_reason = "no_bars"
                direction = None
            else:
                or_cutoff = day_bars["datetime"].iloc[0] + pd.Timedelta(minutes=or_window_min)
                post_or   = day_bars[day_bars["datetime"] > or_cutoff]
                entry_px  = orh if direction == "long" else orl
                if not post_or.empty:
                    trade = _simulate_day(post_or, direction, entry_px, stop_pts, target_pts)
                if trade:
                    trades.append(trade)

        results.append({
            "date":        sess["date"],
            "bias_a":      bias_a,
            "a1":          int(day_bias.get("a1", 0)),
            "a2":          int(day_bias.get("a2", 0)),
            "a3":          int(day_bias.get("a3", 0)),
            "c1_top_div":  c1_top,
            "c1_bot_div":  c1_bot,
            "orh":         orh,
            "orl":         orl,
            "or_range":    or_range,
            "direction":   direction or "skip",
            "skip_reason": skip_reason,
            "trade_taken": trade is not None,
            "exit_reason": trade.exit_reason if trade else "",
            "pnl_pts":     trade.pnl_pts    if trade else 0.0,
        })

    return trades, pd.DataFrame(results)


# ── summary stats ─────────────────────────────────────────────────────────────

def print_summary(trades: list[Trade], sessions: pd.DataFrame) -> None:
    if not trades:
        print("No trades.")
        return

    pnls  = [t.pnl_pts for t in trades]
    wins  = [p for p in pnls if p > 0]
    losses= [p for p in pnls if p <= 0]
    win_r = len(wins) / len(pnls) * 100

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

    # max consecutive losses
    max_streak = cur_streak = 0
    for p in pnls:
        if p <= 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0

    print(f"\n{'='*50}")
    print(f"Trades       : {len(pnls)}")
    print(f"Win rate     : {win_r:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Avg win      : {sum(wins)/len(wins):.1f} pts" if wins else "Avg win : -")
    print(f"Avg loss     : {sum(losses)/len(losses):.1f} pts" if losses else "Avg loss: -")
    print(f"Expectancy   : {sum(pnls)/len(pnls):.2f} pts/trade")
    print(f"Total PnL    : {sum(pnls):.1f} pts")
    print(f"Max Drawdown : -{max_dd:.1f} pts  ({max_dd*200/1000:.1f}k NTD)")
    print(f"Max consec L : {max_streak} 連敗")

    # exit breakdown
    by_exit = sessions[sessions["trade_taken"]].groupby("exit_reason")["pnl_pts"].agg(["count","mean","sum"])
    print(f"\nExit breakdown:\n{by_exit.to_string()}")

    # days skipped
    skipped = sessions[sessions["direction"] == "skip"]
    print(f"\nSkipped days : {len(skipped)}  (no bias or C1 filter)")
    if len(skipped):
        print(skipped["skip_reason"].value_counts().to_string())
    print(f"{'='*50}")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Layer C backtest")
    parser.add_argument("--stop",      type=float, default=STOP_PTS)
    parser.add_argument("--reward",    type=float, default=REWARD_MULT)
    parser.add_argument("--bias-thr",  type=int,   default=BIAS_THRESHOLD)
    parser.add_argument("--or-window", type=int,   default=OR_WINDOW_MIN)
    parser.add_argument("--div-window",type=int,   default=DIV_WINDOW)
    parser.add_argument("--no-c1",     action="store_true", help="Disable C1 filter")
    parser.add_argument("--max-or",    type=float, default=0.0,
                        help="Skip days where OR range exceeds this many pts (0=off)")
    parser.add_argument("--ma-trend",  type=int,   default=0,
                        help="Require open above/below N-day MA before entry (0=off)")
    parser.add_argument("--trades",    help="Save trade log to CSV")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s | %(message)s")

    if not LAYER_A_PATH.exists():
        logger.error("layer_a_daily.csv not found. Run: python -m backend.layer_a")
        return 1

    trades, sessions = run_backtest(
        stop_pts       = args.stop,
        reward_mult    = args.reward,
        bias_threshold = args.bias_thr,
        or_window_min  = args.or_window,
        div_window     = args.div_window,
        use_c1         = not args.no_c1,
        max_or         = args.max_or,
        ma_window      = args.ma_trend,
    )

    print_summary(trades, sessions)

    if args.trades:
        sessions.to_csv(args.trades, index=False)
        logger.info("Trade log saved → %s", args.trades)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
