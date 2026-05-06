"""K-line chart with Fibonacci retracement overlay.

Pure rendering helpers — no Telegram or async dependencies. Given an OHLCV
DataFrame (DatetimeIndex), produce a PNG showing the last N trading days as
candlesticks with 7 Fibonacci retracement levels drawn between the swing
high and swing low of the window.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from loguru import logger

_FIB_LEVELS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
_FIB_COLORS = ("#888888", "#d62728", "#ff7f0e", "#2ca02c",
               "#1f77b4", "#9467bd", "#888888")

# Try to set a CJK-capable font so symbol/name don't render as boxes.
for _font in ("Microsoft JhengHei", "Microsoft YaHei", "PingFang TC",
              "Noto Sans CJK TC", "SimHei"):
    try:
        matplotlib.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break
    except Exception:
        continue


def render_kline_with_fib(
    df: pd.DataFrame,
    symbol: str,
    name: str,
    out_path: Path,
    lookback_days: int = 30,
) -> Path:
    """Render last `lookback_days` candles plus Fibonacci retracement to PNG."""
    if df.empty:
        raise ValueError("empty OHLCV DataFrame")

    window = df.tail(lookback_days).copy()
    if len(window) < 2:
        raise ValueError(f"need at least 2 candles, got {len(window)}")

    high_idx = window["high"].idxmax()
    low_idx = window["low"].idxmin()
    swing_high = float(window.loc[high_idx, "high"])
    swing_low = float(window.loc[low_idx, "low"])
    rng = swing_high - swing_low
    if rng <= 0:
        raise ValueError("flat range — cannot draw Fibonacci")

    # Direction: if the high came AFTER the low → uptrend, retrace from high down.
    # Else downtrend, retrace from low up. Either way 0% sits at the most
    # recent swing extreme.
    uptrend = high_idx > low_idx

    fib_lines = []
    for lvl in _FIB_LEVELS:
        if uptrend:
            price = swing_high - rng * lvl
        else:
            price = swing_low + rng * lvl
        fib_lines.append((lvl, price))

    style = mpf.make_mpf_style(base_mpf_style="charles", rc={"font.size": 9})
    fig, axes = mpf.plot(
        window,
        type="candle",
        style=style,
        volume=True,
        figsize=(11, 7),
        returnfig=True,
        tight_layout=True,
        datetime_format="%m-%d",
        xrotation=0,
    )

    ax = axes[0]
    for (lvl, price), color in zip(fib_lines, _FIB_COLORS):
        ax.axhline(price, color=color, linewidth=1.0, linestyle="--", alpha=0.85)
        ax.text(
            len(window) - 1, price,
            f" {lvl*100:.1f}%  {price:.2f}",
            color=color, fontsize=8, va="center", ha="left",
        )

    direction = "Uptrend" if uptrend else "Downtrend"
    fig.suptitle(
        f"{symbol} {name}  —  Last {len(window)}D K-Line + Fibonacci ({direction})",
        fontsize=12, y=0.995,
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"[chart] rendered {symbol} → {out_path}")
    return out_path
