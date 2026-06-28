"""SMC events → TradingView UDF `marks` payload.

TradingView /marks response shape (column-major):
    {
      "id":              [int|str, ...],
      "time":            [unix_seconds, ...],
      "color":           ["red"|"green"|"#hex"|{border,background}, ...],
      "text":            ["BOS↑", "CHoCH↓", ...],
      "label":           ["B", "C", ...],          # short letter shown on circle
      "labelFontColor":  ["white", ...],
      "minSize":         [30, 30, ...],            # min pixel radius
    }
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.smc_detector import (
    classify_strong_weak,
    compute_trendlines,
    detect_market_structure,
    find_fair_value_gaps,
    find_order_blocks,
    find_swing_points,
    mark_equal_pivots,
)

logger = logging.getLogger("tv-chart.marks")


_COLOR_BOS = "#4cc9f0"
_COLOR_CHOCH = "#ffb454"
_COLOR_SH = "#ef476f"
_COLOR_SL = "#06d6a0"
_COLOR_EQ = "#e7d34d"
_COLOR_OB_BULL = "#3179f5"
_COLOR_OB_BEAR = "#f77c80"
_COLOR_TL_UP_BREAK = "#2dd4bf"
_COLOR_TL_DN_BREAK = "#fb7185"


def _bar_ts(df: pd.DataFrame, bar_idx: int) -> int:
    """UTC seconds (treating naive Shioaji timestamps as UTC for axis display)."""
    if df is None or df.empty or bar_idx < 0 or bar_idx >= len(df):
        return 0
    return int(df.index[bar_idx].value // 1_000_000_000)


def build_marks(df: pd.DataFrame, *, swing_n: int = 10) -> dict[str, list[Any]]:
    """Compute every SMC event mark for `df` and return a UDF /marks payload."""
    if df is None or df.empty or len(df) < swing_n * 2 + 1:
        return _empty_marks()

    structure = detect_market_structure(df, n=swing_n)
    swing_points = structure["swing_points"]
    eq = mark_equal_pivots(swing_points, df)
    sw = classify_strong_weak(structure)
    obs = find_order_blocks(df, lookback=30, max_count=5)
    fvgs = [f for f in find_fair_value_gaps(df) if f["valid"]]
    trendlines = compute_trendlines(df, length=max(8, swing_n - 1))

    ids: list[int] = []
    times: list[int] = []
    colors: list[Any] = []
    texts: list[str] = []
    labels: list[str] = []
    label_font_colors: list[str] = []
    min_sizes: list[int] = []

    def add(time_s: int, color: str, text: str, label: str,
            font: str = "white", size: int = 22) -> None:
        if time_s <= 0:
            return
        ids.append(len(ids))
        times.append(time_s)
        colors.append(color)
        texts.append(text)
        labels.append(label)
        label_font_colors.append(font)
        min_sizes.append(size)

    # ── BOS / CHoCH ──
    for key, color, prefix in (("last_bos", _COLOR_BOS, "BOS"),
                                ("last_choch", _COLOR_CHOCH, "CHoCH")):
        evt = structure.get(key)
        if not evt:
            continue
        try:
            bar_idx = df.index.get_loc(evt["index"])
        except KeyError:
            continue
        if isinstance(bar_idx, slice):
            bar_idx = bar_idx.start
        up = evt["type"].endswith("_UP")
        add(
            _bar_ts(df, bar_idx),
            color=color,
            text=f"{prefix}{'↑' if up else '↓'} @ {evt['price']:.2f}",
            label=prefix[0],
            size=28,
        )

    # ── Swing High / Low ──
    for sh in swing_points.get("swing_highs", []):
        add(_bar_ts(df, sh["bar_idx"]), _COLOR_SH,
            f"Swing High {sh['price']:.2f}", "H", size=14)
    for sl in swing_points.get("swing_lows", []):
        add(_bar_ts(df, sl["bar_idx"]), _COLOR_SL,
            f"Swing Low {sl['price']:.2f}", "L", size=14)

    # ── Equal Highs / Lows (mark the second pivot of each pair) ──
    for _prev, curr in eq.get("equal_highs", []):
        add(_bar_ts(df, curr["bar_idx"]), _COLOR_EQ,
            f"Equal High {curr['price']:.2f}", "EQ", size=16)
    for _prev, curr in eq.get("equal_lows", []):
        add(_bar_ts(df, curr["bar_idx"]), _COLOR_EQ,
            f"Equal Low {curr['price']:.2f}", "EQ", size=16)

    # ── Strong / Weak (annotate the latest swing) ──
    for kind, color, text in (
        ("strong_high", _COLOR_SH, "Strong High"),
        ("weak_high",   "#7c8aa6", "Weak High"),
        ("strong_low",  _COLOR_SL, "Strong Low"),
        ("weak_low",    "#7c8aa6", "Weak Low"),
    ):
        p = sw.get(kind)
        if not p:
            continue
        add(_bar_ts(df, p["bar_idx"]), color, text, kind[0].upper(), size=18)

    # ── Order Blocks (mark their formation bar) ──
    for ob in obs:
        color = _COLOR_OB_BULL if ob["bias"] == "bullish" else _COLOR_OB_BEAR
        text = f"{'Bull' if ob['bias'] == 'bullish' else 'Bear'} OB " \
               f"{ob['bottom']:.2f}–{ob['top']:.2f}"
        add(_bar_ts(df, ob["formed_bar"]), color, text, "OB", size=20)

    # ── Valid FVGs (mark the formed bar) ──
    for f in fvgs:
        color = "#00ff68" if f["bias"] == "bullish" else "#ff0008"
        text = f"{'Bull' if f['bias'] == 'bullish' else 'Bear'} FVG " \
               f"{f['bottom']:.2f}–{f['top']:.2f}"
        add(_bar_ts(df, f["formed_bar"]), color, text, "F", size=16)

    # ── Trendline break events ──
    if trendlines:
        for brk in trendlines.get("upper_breaks", []):
            add(_bar_ts(df, brk["bar_idx"]), _COLOR_TL_UP_BREAK,
                f"Up Trendline Break @ {brk['price']:.2f}", "▲", size=22)
        for brk in trendlines.get("lower_breaks", []):
            add(_bar_ts(df, brk["bar_idx"]), _COLOR_TL_DN_BREAK,
                f"Down Trendline Break @ {brk['price']:.2f}", "▼", size=22)

    return {
        "id": ids,
        "time": times,
        "color": colors,
        "text": texts,
        "label": labels,
        "labelFontColor": label_font_colors,
        "minSize": min_sizes,
    }


def _empty_marks() -> dict[str, list[Any]]:
    return {
        "id": [], "time": [], "color": [], "text": [],
        "label": [], "labelFontColor": [], "minSize": [],
    }
