"""HTML report generator for SMC signals.

Embeds a lightweight-charts candle chart with:
  * Internal + Swing structure markers (BOS / CHoCH)
  * Swing High / Low markers
  * Equal Highs / Equal Lows
  * Fair Value Gaps (green = bullish, red = bearish; valid = unmitigated)
  * Strong / Weak High & Low labels
  * Demand / Supply zones (from the signal payload)

Uses string.Template (not f-strings) so CSS / JS braces don't fight Python.
"""
from __future__ import annotations

import base64
import io
import json
import logging
from datetime import datetime
from html import escape
from string import Template
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")  # headless, must precede pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from backend.smc_detector import (
    SMCSignal,
    classify_strong_weak,
    compute_mtf_levels,
    compute_premium_discount,
    compute_trendlines,
    detect_dual_structure,
    detect_market_structure,
    find_fair_value_gaps,
    find_order_blocks,
    find_swing_points,
    mark_equal_pivots,
)

logger = logging.getLogger("smc-report")


# ── advice ────────────────────────────────────────────────────────────────────

def _advice(signal: SMCSignal) -> str:
    st = signal.signal_type
    ms = signal.market_structure
    dz = signal.demand_zone
    sz = signal.supply_zone

    if st == "BOS_UP" and ms == "bullish":
        if dz:
            return (
                f"上升結構延續。等回測 Demand Zone "
                f"{dz['bottom']:.2f}–{dz['top']:.2f} 進場，止損設於 "
                f"{dz['bottom']:.2f} 下方。"
            )
        return "上升結構延續，但無有效需求區。觀望回測訊號再考慮進場。"

    if st == "BOS_DOWN" and ms == "bearish":
        if sz:
            return (
                f"下降結構延續。等反彈至 Supply Zone "
                f"{sz['bottom']:.2f}–{sz['top']:.2f} 放空，止損設於 "
                f"{sz['top']:.2f} 上方。"
            )
        return "下降結構延續，但無有效供給區。觀望反彈訊號再考慮放空。"

    if st == "CHoCH_DOWN":
        return "警告：結構轉弱，多頭止盈並關注是否形成新空頭趨勢。避免逆勢加碼。"
    if st == "CHoCH_UP":
        return "警告：結構轉強，空頭止盈並關注是否形成新多頭趨勢。等回測 Demand Zone 進場。"

    return "結構訊號出現，等待確認後再行動。"


# ── small helpers ─────────────────────────────────────────────────────────────

def _fmt_zone(z: Optional[dict]) -> str:
    if not z:
        return "—"
    return f"{z['bottom']:.2f} – {z['top']:.2f}"


def _stars(strength: int) -> str:
    s = max(1, min(int(strength), 3))
    return "★" * s + "☆" * (3 - s)


def _pill_class(signal_type: str) -> str:
    if signal_type.endswith("_UP"):
        return "up"
    if signal_type.endswith("_DOWN"):
        return "down"
    return "warn"


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td class="k">{escape(label)}</td>'
        f'<td class="v">{value}</td></tr>'
    )


def _to_unix_seconds(ts: Any) -> int:
    """Convert a pandas Timestamp / datetime to integer seconds.

    Naive timestamps are treated as already-UTC for chart purposes so the
    x-axis renders the original local clock time (e.g. Taiwan trading hours)
    regardless of the viewer's tz.
    """
    if isinstance(ts, pd.Timestamp):
        if ts.tz is not None:
            ts = ts.tz_convert("Asia/Taipei").tz_localize(None)
        try:
            return int(ts.value // 1_000_000_000)
        except Exception:
            return 0
    if isinstance(ts, datetime):
        try:
            return int(pd.Timestamp(ts).value // 1_000_000_000)
        except Exception:
            return 0
    return 0


def _bar_idx_to_time(df: pd.DataFrame, bar_idx: int) -> int:
    """Convert positional bar index → UTC seconds for chart markers."""
    if df is None or df.empty or bar_idx < 0 or bar_idx >= len(df):
        return 0
    return _to_unix_seconds(df.index[bar_idx])


# ── chart payload builders ────────────────────────────────────────────────────

def _chart_data(df: pd.DataFrame) -> list[dict]:
    """Build lightweight-charts candlestick data; sorted, deduped by time."""
    if df is None or df.empty:
        return []
    rows: list[dict] = []
    for ts, row in df.iterrows():
        rows.append({
            "time": _to_unix_seconds(ts),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    rows.sort(key=lambda r: r["time"])
    seen: set[int] = set()
    out: list[dict] = []
    for r in rows:
        if r["time"] in seen:
            continue
        seen.add(r["time"])
        out.append(r)
    return out


def _swing_markers(swing_points: dict, df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for sh in swing_points.get("swing_highs", []):
        out.append({
            "time": _bar_idx_to_time(df, sh["bar_idx"]),
            "position": "aboveBar",
            "color": "#ef476f",
            "shape": "arrowDown",
            "text": "",
        })
    for sl in swing_points.get("swing_lows", []):
        out.append({
            "time": _bar_idx_to_time(df, sl["bar_idx"]),
            "position": "belowBar",
            "color": "#06d6a0",
            "shape": "arrowUp",
            "text": "",
        })
    return out


def _structure_markers(
    structure_result: dict,
    df: pd.DataFrame,
    *,
    is_internal: bool,
) -> list[dict]:
    """BOS / CHoCH markers for one structure layer."""
    out: list[dict] = []
    bos_color = "#4cc9f0"
    ch_color = "#ffb454"
    size_hint = "" if is_internal else ""

    for key, color in (("last_bos", bos_color), ("last_choch", ch_color)):
        evt = structure_result.get(key)
        if not evt:
            continue
        going_up = evt["type"].endswith("_UP")
        label = ("BOS" if key == "last_bos" else "CHoCH")
        label = f"i{label}" if is_internal else label
        label = label + ("↑" if going_up else "↓")
        out.append({
            "time": _to_unix_seconds(evt["index"]),
            "position": "aboveBar" if going_up else "belowBar",
            "color": color,
            "shape": "circle" if is_internal else "square",
            "text": label,
        })
    return out


def _equal_markers(equal_data: dict, df: pd.DataFrame) -> list[dict]:
    """Markers for the *second* pivot of each equal pair (where confirmation lands)."""
    out: list[dict] = []
    for _prev, curr in equal_data.get("equal_highs", []):
        out.append({
            "time": _bar_idx_to_time(df, curr["bar_idx"]),
            "position": "aboveBar",
            "color": "#e7d34d",
            "shape": "circle",
            "text": "EQH",
        })
    for _prev, curr in equal_data.get("equal_lows", []):
        out.append({
            "time": _bar_idx_to_time(df, curr["bar_idx"]),
            "position": "belowBar",
            "color": "#e7d34d",
            "shape": "circle",
            "text": "EQL",
        })
    return out


def _strong_weak_markers(sw: dict, df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for kind, color, position, text in (
        ("strong_high", "#ef476f", "aboveBar", "Strong High"),
        ("weak_high",   "#7c8aa6", "aboveBar", "Weak High"),
        ("strong_low",  "#06d6a0", "belowBar", "Strong Low"),
        ("weak_low",    "#7c8aa6", "belowBar", "Weak Low"),
    ):
        p = sw.get(kind)
        if not p:
            continue
        out.append({
            "time": _bar_idx_to_time(df, p["bar_idx"]),
            "position": position,
            "color": color,
            "shape": "square",
            "text": text,
        })
    return out


def _equal_lines(equal_data: dict, df: pd.DataFrame) -> list[dict]:
    """Two-point line segments joining equal pivots (rendered as line series)."""
    out: list[dict] = []
    for prev, curr in equal_data.get("equal_highs", []):
        out.append({
            "kind": "eqh",
            "from": _bar_idx_to_time(df, prev["bar_idx"]),
            "to":   _bar_idx_to_time(df, curr["bar_idx"]),
            "price": float((prev["price"] + curr["price"]) / 2),
        })
    for prev, curr in equal_data.get("equal_lows", []):
        out.append({
            "kind": "eql",
            "from": _bar_idx_to_time(df, prev["bar_idx"]),
            "to":   _bar_idx_to_time(df, curr["bar_idx"]),
            "price": float((prev["price"] + curr["price"]) / 2),
        })
    return out


def _fvg_payload(
    fvgs: list[dict],
    df: pd.DataFrame,
    *,
    max_items: int = 10,
    only_valid: bool = True,
) -> list[dict]:
    """Pack FVGs for JS rendering: from `formed_at` time → end of chart."""
    out: list[dict] = []
    if df is None or df.empty:
        return out
    end_t = _to_unix_seconds(df.index[-1])
    pool = [f for f in fvgs if (not only_valid) or f["valid"]]
    pool = sorted(pool, key=lambda f: f["formed_bar"])[-max_items:]
    for f in pool:
        out.append({
            "bias": f["bias"],
            "top": float(f["top"]),
            "bottom": float(f["bottom"]),
            "from": _bar_idx_to_time(df, f["formed_bar"]),
            "to": end_t,
            "valid": bool(f["valid"]),
        })
    return out


def _ob_payload(obs: list[dict], df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    end_t = _to_unix_seconds(df.index[-1])
    out: list[dict] = []
    for o in obs:
        out.append({
            "bias": o["bias"],
            "top": float(o["top"]),
            "bottom": float(o["bottom"]),
            "from": _bar_idx_to_time(df, o["formed_bar"]),
            "to": end_t,
        })
    return out


def _trendline_breaks_markers(tl: Optional[dict], df: pd.DataFrame) -> list[dict]:
    """Markers for upward/downward trendline break events."""
    out: list[dict] = []
    if not tl:
        return out
    for evt in tl.get("upper_breaks", []):
        out.append({
            "time": _bar_idx_to_time(df, evt["bar_idx"]),
            "position": "belowBar",
            "color": "#2dd4bf",
            "shape": "square",
            "text": "▲BRK",
        })
    for evt in tl.get("lower_breaks", []):
        out.append({
            "time": _bar_idx_to_time(df, evt["bar_idx"]),
            "position": "aboveBar",
            "color": "#fb7185",
            "shape": "square",
            "text": "▼BRK",
        })
    return out


def _trendline_series(tl: Optional[dict], df: pd.DataFrame) -> dict:
    """Pack the upper/lower trendline arrays as lightweight-charts line data."""
    if not tl or df is None or df.empty:
        return {"upper": [], "lower": []}
    upper = []
    lower = []
    for t in range(len(df)):
        ts = _to_unix_seconds(df.index[t])
        u = tl["upper"][t]
        l = tl["lower"][t]
        if not np.isnan(u):
            upper.append({"time": ts, "value": float(u)})
        if not np.isnan(l):
            lower.append({"time": ts, "value": float(l)})
    return {"upper": upper, "lower": lower}


def _build_chart_context(
    chart_df: pd.DataFrame,
    *,
    internal_n: int,
    swing_n: int,
    daily_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """One-shot compute of every annotation the chart needs."""
    empty = {
        "candles": [], "markers": [], "fvgs": [], "eq_lines": [],
        "order_blocks": [], "pd_zones": None, "trendlines_upper": [],
        "trendlines_lower": [], "mtf": None,
    }
    if chart_df is None or chart_df.empty:
        return empty

    dual = detect_dual_structure(chart_df, internal_n=internal_n, swing_n=swing_n)
    swing_struct = dual["swing"]
    internal_struct = dual["internal"]

    swing_points = swing_struct["swing_points"]
    eq = mark_equal_pivots(swing_points, chart_df)
    sw = classify_strong_weak(swing_struct)
    fvgs = find_fair_value_gaps(chart_df)
    obs = find_order_blocks(chart_df, lookback=30, max_count=5)
    pd_zones = compute_premium_discount(swing_points, chart_df)
    trendlines = compute_trendlines(chart_df, length=max(8, swing_n - 1))
    mtf = compute_mtf_levels(daily_df) if daily_df is not None else None
    tl_series = _trendline_series(trendlines, chart_df)

    markers: list[dict] = []
    markers += _swing_markers(swing_points, chart_df)
    markers += _structure_markers(swing_struct, chart_df, is_internal=False)
    markers += _structure_markers(internal_struct, chart_df, is_internal=True)
    markers += _equal_markers(eq, chart_df)
    markers += _strong_weak_markers(sw, chart_df)
    markers += _trendline_breaks_markers(trendlines, chart_df)
    markers.sort(key=lambda m: m["time"])

    return {
        "candles": _chart_data(chart_df),
        "markers": markers,
        "fvgs": _fvg_payload(fvgs, chart_df),
        "eq_lines": _equal_lines(eq, chart_df),
        "strong_weak": sw,
        "fvg_total": len(fvgs),
        "eq_total": len(eq.get("equal_highs", [])) + len(eq.get("equal_lows", [])),
        "order_blocks": _ob_payload(obs, chart_df),
        "ob_total": len(obs),
        "pd_zones": pd_zones,
        "trendlines_upper": tl_series["upper"],
        "trendlines_lower": tl_series["lower"],
        "trendline_breaks_total": (len(trendlines.get("upper_breaks", [])) +
                                    len(trendlines.get("lower_breaks", []))) if trendlines else 0,
        "mtf": mtf,
    }


# ── static PNG renderer (fallback for Telegram inline preview) ────────────────

_BG = "#070a0f"
_PANEL = "#0d1320"
_GRID = "#1a2235"
_TEXT = "#e6edf6"
_MUTED = "#7c8aa6"
_UP_COLOR = "#06d6a0"
_DOWN_COLOR = "#ef476f"
_BOS = "#4cc9f0"
_CHOCH = "#ffb454"
_EQ = "#e7d34d"


def render_chart_png(
    chart_df: pd.DataFrame,
    *,
    signal: SMCSignal,
    internal_n: int = 5,
    swing_n: int = 10,
    figsize: tuple[float, float] = (12, 6),
    dpi: int = 110,
    daily_df: Optional[pd.DataFrame] = None,
) -> bytes:
    """Render the SMC chart to a self-contained PNG.

    Drawn elements (matching the LuxAlgo-style overlay):
      * Candlesticks
      * Demand / Supply zones (full-width semi-transparent bands)
      * Valid FVGs (green = bullish, red = bearish; extend from formed bar onward)
      * Swing high ▼ / swing low ▲ markers
      * Swing BOS / CHoCH text annotations
      * EQH / EQL dashed connectors
      * Strong / Weak High / Low labels on the right edge
    """
    if chart_df is None or chart_df.empty:
        return b""

    df = chart_df.copy()
    n = len(df)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    # Run all detectors once.
    swing_struct = detect_market_structure(df, n=swing_n)
    sp = swing_struct["swing_points"]
    eq = mark_equal_pivots(sp, df)
    sw = classify_strong_weak(swing_struct)
    fvgs = find_fair_value_gaps(df)
    valid_fvgs = [f for f in fvgs if f["valid"]]
    obs = find_order_blocks(df, lookback=30, max_count=5)
    pd_zones = compute_premium_discount(sp, df)
    trendlines = compute_trendlines(df, length=max(8, swing_n - 1))
    mtf = compute_mtf_levels(daily_df) if daily_df is not None else None

    fig, ax = plt.subplots(figsize=figsize, facecolor=_BG)
    ax.set_facecolor(_BG)

    # ── Demand / Supply zones (signal-derived) ──
    if signal.demand_zone:
        dz = signal.demand_zone
        ax.add_patch(Rectangle(
            (-0.5, dz["bottom"]),
            n + 0.5,
            dz["top"] - dz["bottom"],
            facecolor=_UP_COLOR, alpha=0.10, edgecolor=_UP_COLOR,
            linewidth=0.7, zorder=1,
        ))
    if signal.supply_zone:
        sz = signal.supply_zone
        ax.add_patch(Rectangle(
            (-0.5, sz["bottom"]),
            n + 0.5,
            sz["top"] - sz["bottom"],
            facecolor=_DOWN_COLOR, alpha=0.10, edgecolor=_DOWN_COLOR,
            linewidth=0.7, zorder=1,
        ))

    # ── FVG bands ──
    for f in valid_fvgs:
        color = "#00ff68" if f["bias"] == "bullish" else "#ff0008"
        fb = f["formed_bar"]
        ax.add_patch(Rectangle(
            (fb - 0.5, f["bottom"]),
            (n - fb) + 0.5,
            f["top"] - f["bottom"],
            facecolor=color, alpha=0.18, edgecolor=color,
            linewidth=0.6, zorder=2,
        ))

    # ── Order Blocks (max 5 valid) ──
    for ob in obs:
        bull = ob["bias"] == "bullish"
        color = "#3179f5" if bull else "#f77c80"
        fb = ob["formed_bar"]
        ax.add_patch(Rectangle(
            (fb - 0.5, ob["bottom"]),
            (n - fb) + 0.5,
            ob["top"] - ob["bottom"],
            facecolor=color, alpha=0.22, edgecolor=color,
            linewidth=0.8, zorder=2,
        ))
        ax.annotate(
            "Bull OB" if bull else "Bear OB",
            xy=(fb, ob["top"] if bull else ob["bottom"]),
            xytext=(2, 2 if bull else -10),
            textcoords="offset points",
            color=color, fontsize=7, fontweight="bold", zorder=7,
        )

    # ── Premium / Equilibrium / Discount thin bands (LuxAlgo 5% spec) ──
    if pd_zones:
        for kind, color in (
            ("premium",     "#ef476f"),
            ("equilibrium", "#878b94"),
            ("discount",    "#06d6a0"),
        ):
            z = pd_zones[kind]
            ax.add_patch(Rectangle(
                (-0.5, z["bottom"]),
                n + 0.5,
                z["top"] - z["bottom"],
                facecolor=color, alpha=0.18, edgecolor=color,
                linewidth=0.5, zorder=1,
            ))
            ax.annotate(
                kind.capitalize(),
                xy=(n - 1, (z["top"] + z["bottom"]) / 2),
                xytext=(8, 0), textcoords="offset points",
                ha="left", va="center",
                color=color, fontsize=8, fontweight="bold", zorder=7,
            )

    # ── Trendlines (upper down-slope + lower up-slope) ──
    if trendlines is not None:
        bar_x = np.arange(n)
        upper = trendlines["upper"]
        lower = trendlines["lower"]
        ax.plot(bar_x, upper, color="#fb7185", linewidth=1.0,
                linestyle="--", alpha=0.85, zorder=6)
        ax.plot(bar_x, lower, color="#2dd4bf", linewidth=1.0,
                linestyle="--", alpha=0.85, zorder=6)
        for brk in trendlines.get("upper_breaks", []):
            ax.annotate(
                "▲BRK", xy=(brk["bar_idx"], brk["price"]),
                xytext=(0, -14), textcoords="offset points",
                ha="center", color="#2dd4bf", fontsize=8, fontweight="bold",
                bbox=dict(facecolor=_PANEL, edgecolor="#2dd4bf",
                          boxstyle="round,pad=0.2"),
                zorder=9,
            )
        for brk in trendlines.get("lower_breaks", []):
            ax.annotate(
                "▼BRK", xy=(brk["bar_idx"], brk["price"]),
                xytext=(0, 14), textcoords="offset points",
                ha="center", color="#fb7185", fontsize=8, fontweight="bold",
                bbox=dict(facecolor=_PANEL, edgecolor="#fb7185",
                          boxstyle="round,pad=0.2"),
                zorder=9,
            )

    # ── MTF horizontal price lines (PDH/PDL/PWH/PWL) ──
    if mtf:
        for key, color, label in (
            ("pdh", "#4cc9f0", "PDH"),
            ("pdl", "#4cc9f0", "PDL"),
            ("pwh", "#a78bfa", "PWH"),
            ("pwl", "#a78bfa", "PWL"),
        ):
            v = mtf.get(key)
            if v is None:
                continue
            ax.axhline(v, color=color, linestyle="--",
                       linewidth=0.8, alpha=0.7, zorder=3)
            ax.annotate(
                f"{label} {v:.0f}", xy=(0, v),
                xytext=(2, 2), textcoords="offset points",
                color=color, fontsize=7, fontweight="bold", zorder=7,
            )

    # ── Candles ──
    # Vectorized wick drawing via LineCollection — keeps the figure responsive
    # even with 1000+ bars (1m × 5 days).
    from matplotlib.collections import LineCollection, PatchCollection

    width = 0.7 if n <= 200 else max(0.3, 60.0 / n)
    wick_linewidth = 1.0 if n <= 200 else 0.6
    up_mask = c >= o
    up_color = _UP_COLOR
    dn_color = _DOWN_COLOR
    colors = np.where(up_mask, up_color, dn_color)

    wick_segs = [((i, l[i]), (i, h[i])) for i in range(n)]
    ax.add_collection(LineCollection(
        wick_segs, colors=colors.tolist(), linewidths=wick_linewidth, zorder=4
    ))

    body_patches = []
    body_colors = []
    for i in range(n):
        bottom = min(o[i], c[i])
        height = max(abs(c[i] - o[i]), (h[i] - l[i]) * 0.02)
        body_patches.append(Rectangle((i - width / 2, bottom), width, height))
        body_colors.append(colors[i])
    body_pc = PatchCollection(body_patches, facecolors=body_colors,
                              edgecolors=body_colors, linewidths=0.5, zorder=5)
    ax.add_collection(body_pc)

    # ── Swing point markers ──
    for s in sp.get("swing_highs", []):
        ax.annotate(
            "▼", xy=(s["bar_idx"], s["price"]),
            xytext=(0, 10), textcoords="offset points",
            ha="center", va="bottom", color=_DOWN_COLOR,
            fontsize=11, zorder=8,
        )
    for s in sp.get("swing_lows", []):
        ax.annotate(
            "▲", xy=(s["bar_idx"], s["price"]),
            xytext=(0, -12), textcoords="offset points",
            ha="center", va="top", color=_UP_COLOR,
            fontsize=11, zorder=8,
        )

    # ── BOS / CHoCH event labels (swing structure) ──
    for key, label, color in (("last_bos", "BOS", _BOS), ("last_choch", "CHoCH", _CHOCH)):
        evt = swing_struct.get(key)
        if not evt:
            continue
        try:
            bar_idx = df.index.get_loc(evt["index"])
        except KeyError:
            continue
        if isinstance(bar_idx, slice):
            bar_idx = bar_idx.start
        going_up = evt["type"].endswith("_UP")
        arrow = "↑" if going_up else "↓"
        ax.annotate(
            f"{label}{arrow}",
            xy=(bar_idx, evt["price"]),
            xytext=(0, 26 if going_up else -28),
            textcoords="offset points",
            ha="center",
            va="bottom" if going_up else "top",
            color=color, fontsize=9, fontweight="bold",
            bbox=dict(facecolor=_PANEL, edgecolor=color,
                      boxstyle="round,pad=0.25"),
            zorder=9,
        )

    # ── EQH / EQL dashed connectors ──
    for prev, curr in eq.get("equal_highs", []):
        avg = (prev["price"] + curr["price"]) / 2
        ax.plot([prev["bar_idx"], curr["bar_idx"]], [avg, avg],
                color=_EQ, linestyle="--", linewidth=1.0, zorder=6)
        ax.annotate(
            "EQH", xy=(curr["bar_idx"], avg),
            xytext=(4, 2), textcoords="offset points",
            color=_EQ, fontsize=8, fontweight="bold", zorder=7,
        )
    for prev, curr in eq.get("equal_lows", []):
        avg = (prev["price"] + curr["price"]) / 2
        ax.plot([prev["bar_idx"], curr["bar_idx"]], [avg, avg],
                color=_EQ, linestyle="--", linewidth=1.0, zorder=6)
        ax.annotate(
            "EQL", xy=(curr["bar_idx"], avg),
            xytext=(4, -10), textcoords="offset points",
            color=_EQ, fontsize=8, fontweight="bold", zorder=7,
        )

    # ── Strong / Weak labels on right edge ──
    for kind, color, text in (
        ("strong_high", _DOWN_COLOR, "Strong High"),
        ("weak_high",   _MUTED,      "Weak High"),
        ("strong_low",  _UP_COLOR,   "Strong Low"),
        ("weak_low",    _MUTED,      "Weak Low"),
    ):
        p = sw.get(kind)
        if not p:
            continue
        ax.annotate(
            text, xy=(n - 1, p["price"]),
            xytext=(10, 0), textcoords="offset points",
            ha="left", va="center",
            color=color, fontsize=9, fontweight="bold",
            bbox=dict(facecolor=_PANEL, edgecolor=color,
                      boxstyle="round,pad=0.25"),
            zorder=9,
        )

    # ── Axes styling ──
    ax.set_xlim(-1, n + 8)  # space for right-side labels
    pad_y = (h.max() - l.min()) * 0.05
    ax.set_ylim(l.min() - pad_y, h.max() + pad_y)
    ax.tick_params(colors=_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.4, alpha=0.6)
    ax.set_title(
        f"{signal.symbol}  •  {signal.signal_type}  •  {signal.timeframe}",
        color=_TEXT, fontsize=12, loc="left", pad=10, fontweight="bold",
    )

    # X-axis ticks: show ~10 evenly-spaced labels. When the data spans multiple
    # trading days (e.g. 1m × 1 week), include the date in the label.
    step = max(n // 10, 1)
    positions = list(range(0, n, step))
    is_intraday = signal.timeframe in ("1m", "3m", "5m", "15m")
    unique_dates = sorted({df.index[i].date() for i in positions}) if hasattr(df.index[0], "date") else []
    multi_day = len(unique_dates) > 1
    if not is_intraday:
        fmt = "%m-%d"
    elif multi_day:
        fmt = "%m-%d\n%H:%M"
    else:
        fmt = "%H:%M"
    labels = []
    for i in positions:
        ts = df.index[i]
        labels.append(ts.strftime(fmt) if hasattr(ts, "strftime") else str(ts))
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=7 if multi_day else 8)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=_BG, edgecolor="none")
    plt.close(fig)
    return buf.getvalue()


def _png_data_uri(png_bytes: bytes) -> str:
    if not png_bytes:
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ── template ──────────────────────────────────────────────────────────────────

_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC｜${symbol}｜${signal_type}</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root {
    --bg: #070a0f;
    --panel: #0d1320;
    --line: #1a2235;
    --text: #e6edf6;
    --muted: #7c8aa6;
    --accent: #4cc9f0;
    --warn: #ffb454;
    --bad: #ef476f;
    --good: #06d6a0;
    --eq: #e7d34d;
  }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--text);
    font-family: "Space Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .wrap { max-width: 960px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 22px; letter-spacing: 1px; margin: 0 0 4px; }
  .ts { color: var(--muted); font-size: 12px; }
  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 18px 20px; margin: 16px 0;
  }
  .panel h2 {
    font-size: 13px; letter-spacing: 2px; text-transform: uppercase;
    color: var(--muted); margin: 0 0 12px;
  }
  #chart { width: 100%; min-height: 480px; position: relative; }
  #chart-fallback { display: block; width: 100%; height: auto; border-radius: 6px; }
  .empty-chart {
    color: var(--muted); padding: 170px 0; text-align: center;
    font-size: 13px; border: 1px dashed var(--line); border-radius: 6px;
  }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 6px 0; font-size: 14px; }
  td.k { color: var(--muted); width: 40%; }
  td.v { color: var(--text); text-align: right; font-weight: bold; }
  .pill {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 11px; letter-spacing: 1px; margin-right: 6px;
  }
  .pill.up   { background: rgba(6,214,160,0.15); color: var(--good); border: 1px solid var(--good); }
  .pill.down { background: rgba(239,71,111,0.15); color: var(--bad);  border: 1px solid var(--bad); }
  .pill.warn { background: rgba(255,180,84,0.15); color: var(--warn); border: 1px solid var(--warn); }
  .strength { color: var(--accent); letter-spacing: 4px; font-size: 18px; }
  .advice { font-size: 15px; line-height: 1.6; color: var(--text); }
  .notice {
    background: rgba(255,180,84,0.08); border: 1px solid var(--warn);
    color: var(--warn); padding: 8px 12px; border-radius: 6px; margin: 12px 0;
    font-size: 12px;
  }
  .footer { color: var(--muted); font-size: 11px; line-height: 1.6; margin-top: 24px; }
  .legend {
    display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px;
    font-size: 11px; color: var(--muted);
  }
  .legend span::before {
    content: ""; display: inline-block; width: 10px; height: 10px;
    border-radius: 2px; margin-right: 4px; vertical-align: middle;
  }
  .legend .sh::before     { background: #ef476f; }
  .legend .sl::before     { background: #06d6a0; }
  .legend .bos::before    { background: #4cc9f0; }
  .legend .choch::before  { background: #ffb454; }
  .legend .eq::before     { background: var(--eq); }
  .legend .fvgb::before   { background: rgba(0,255,104,0.30); }
  .legend .fvgs::before   { background: rgba(255,0,8,0.30); }
  .legend .dz::before     { background: rgba(6,214,160,0.45); }
  .legend .sz::before     { background: rgba(239,71,111,0.45); }
  .legend .obb::before    { background: rgba(49,121,245,0.45); }
  .legend .obs::before    { background: rgba(247,124,128,0.45); }
  .legend .pmm::before    { background: rgba(239,71,111,0.45); }
  .legend .dsc::before    { background: rgba(6,214,160,0.45); }
  .legend .tlu::before    { background: #fb7185; }
  .legend .tld::before    { background: #2dd4bf; }
  .legend .mtf::before    { background: #4cc9f0; }
  .stats {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 12px;
  }
  .stat {
    background: rgba(255,255,255,0.02); border: 1px solid var(--line);
    border-radius: 6px; padding: 8px 10px; text-align: center;
  }
  .stat .n { font-size: 18px; color: var(--text); font-weight: bold; }
  .stat .l { font-size: 10px; color: var(--muted); letter-spacing: 1px; }
</style>
</head>
<body>
  <div class="wrap">
    <h1>${symbol} <span class="pill ${pill_class}">${signal_type}</span></h1>
    <div class="ts">產生時間：${ts}（${timeframe}）</div>
    ${notice}

    <div class="panel">
      <h2>K 線圖（最近 ${bars_shown} 根）</h2>
      <div id="chart">${chart_fallback_img}</div>
      <div class="legend">
        <span class="sh">Swing High ▼</span>
        <span class="sl">Swing Low ▲</span>
        <span class="bos">BOS</span>
        <span class="choch">CHoCH</span>
        <span class="eq">EQH / EQL</span>
        <span class="fvgb">Bull FVG</span>
        <span class="fvgs">Bear FVG</span>
        <span class="obb">Bull OB</span>
        <span class="obs">Bear OB</span>
        <span class="pmm">Premium</span>
        <span class="dsc">Discount</span>
        <span class="tlu">↘ Trendline</span>
        <span class="tld">↗ Trendline</span>
        <span class="mtf">MTF P-D-W H/L</span>
      </div>
      <div class="stats">
        <div class="stat"><div class="n">${swing_count}</div><div class="l">SWINGS</div></div>
        <div class="stat"><div class="n">${fvg_count}</div><div class="l">VALID FVG</div></div>
        <div class="stat"><div class="n">${ob_count}</div><div class="l">VALID OB</div></div>
        <div class="stat"><div class="n">${tl_break_count}</div><div class="l">TL BREAKS</div></div>
      </div>
    </div>

    <div class="panel">
      <h2>強度</h2>
      <div class="strength">${strength}</div>
    </div>

    <div class="panel">
      <h2>價格資訊</h2>
      <table>${rows_price}</table>
    </div>

    <div class="panel">
      <h2>市場結構</h2>
      <table>${rows_struct}</table>
    </div>

    <div class="panel">
      <h2>關鍵價區</h2>
      <table>${rows_zones}</table>
    </div>

    <div class="panel">
      <h2>操作建議</h2>
      <div class="advice">${advice}</div>
    </div>

    <div class="footer">
      本報告為自動產生之技術分析訊號，僅供研究參考，不構成任何投資建議。<br>
      盈虧自負，投資前請審慎評估自身風險承受能力。<br>
      Generated at ${generated_at} by smc_report.
    </div>
  </div>

<script>
(function () {
  var candles      = ${candles_json};
  var markers      = ${markers_json};
  var fvgs         = ${fvgs_json};
  var eqLines      = ${eq_lines_json};
  var demand       = ${demand_json};
  var supply       = ${supply_json};
  var orderBlocks  = ${order_blocks_json};
  var pdZones      = ${pd_zones_json};
  var tlUpper      = ${tl_upper_json};
  var tlLower      = ${tl_lower_json};
  var mtf          = ${mtf_json};

  var container = document.getElementById('chart');

  if (!candles || candles.length === 0) {
    // leave PNG fallback in place; just return.
    return;
  }
  if (typeof LightweightCharts === 'undefined') {
    // CDN didn't load — keep the PNG fallback visible.
    return;
  }

  // Live JS path: remove PNG fallback so the canvas takes its place.
  var fb = document.getElementById('chart-fallback');
  if (fb) fb.remove();

  var chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 480,
    layout: {
      background: { type: 'solid', color: '#070a0f' },
      textColor:  '#e6edf6',
    },
    grid: {
      vertLines: { color: '#1a2235' },
      horzLines: { color: '#1a2235' },
    },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      borderColor: '#1a2235',
    },
    rightPriceScale: { borderColor: '#1a2235' },
    crosshair: { mode: 0 },
  });

  // ── Fair Value Gap bands ──
  fvgs.forEach(function (g) {
    var bull = g.bias === 'bullish';
    var color = bull ? 'rgba(0, 255, 104, 1)' : 'rgba(255, 0, 8, 1)';
    var fill1 = bull ? 'rgba(0, 255, 104, 0.25)' : 'rgba(255, 0, 8, 0.25)';
    var fill2 = bull ? 'rgba(0, 255, 104, 0.05)' : 'rgba(255, 0, 8, 0.05)';

    // band runs from g.from → g.to between g.bottom and g.top
    var series = chart.addBaselineSeries({
      baseValue: { type: 'price', price: g.bottom },
      topLineColor:    color,
      topFillColor1:   fill1,
      topFillColor2:   fill2,
      bottomLineColor: 'rgba(0,0,0,0)',
      bottomFillColor1:'rgba(0,0,0,0)',
      bottomFillColor2:'rgba(0,0,0,0)',
      priceLineVisible: false,
      lastValueVisible: false,
      lineWidth: 1,
    });
    // limit data to the FVG's time window so it visually looks like a box
    var pts = candles.filter(function (c) { return c.time >= g.from && c.time <= g.to; })
                     .map(function (c) { return { time: c.time, value: g.top }; });
    if (pts.length >= 2) series.setData(pts);
  });

  // ── Demand zone (from signal) ──
  if (demand) {
    var dz = chart.addBaselineSeries({
      baseValue: { type: 'price', price: demand.bottom },
      topLineColor:   'rgba(6, 214, 160, 0.7)',
      topFillColor1:  'rgba(6, 214, 160, 0.30)',
      topFillColor2:  'rgba(6, 214, 160, 0.05)',
      bottomLineColor:'rgba(0,0,0,0)',
      bottomFillColor1:'rgba(0,0,0,0)',
      bottomFillColor2:'rgba(0,0,0,0)',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    dz.setData(candles.map(function (d) { return { time: d.time, value: demand.top }; }));
  }

  // ── Supply zone (from signal) ──
  if (supply) {
    var sz = chart.addBaselineSeries({
      baseValue: { type: 'price', price: supply.top },
      topLineColor:   'rgba(0,0,0,0)',
      topFillColor1:  'rgba(0,0,0,0)',
      topFillColor2:  'rgba(0,0,0,0)',
      bottomLineColor:'rgba(239, 71, 111, 0.7)',
      bottomFillColor1:'rgba(239, 71, 111, 0.30)',
      bottomFillColor2:'rgba(239, 71, 111, 0.05)',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    sz.setData(candles.map(function (d) { return { time: d.time, value: supply.bottom }; }));
  }

  // ── EQH / EQL connecting line segments ──
  eqLines.forEach(function (s) {
    if (!s.from || !s.to || s.from === s.to) return;
    var seg = chart.addLineSeries({
      color: '#e7d34d',
      lineWidth: 1,
      lineStyle: 2,   // 2 = dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    var pts = candles.filter(function (c) { return c.time >= s.from && c.time <= s.to; })
                     .map(function (c) { return { time: c.time, value: s.price }; });
    if (pts.length >= 2) seg.setData(pts);
  });

  // ── Order Blocks (5 most recent valid) ──
  orderBlocks.forEach(function (ob) {
    var bull = ob.bias === 'bullish';
    var color = bull ? 'rgba(49, 121, 245, 1)' : 'rgba(247, 124, 128, 1)';
    var fill1 = bull ? 'rgba(49, 121, 245, 0.28)' : 'rgba(247, 124, 128, 0.28)';
    var fill2 = bull ? 'rgba(49, 121, 245, 0.06)' : 'rgba(247, 124, 128, 0.06)';
    var series = chart.addBaselineSeries({
      baseValue: { type: 'price', price: ob.bottom },
      topLineColor:    color,
      topFillColor1:   fill1,
      topFillColor2:   fill2,
      bottomLineColor: 'rgba(0,0,0,0)',
      bottomFillColor1:'rgba(0,0,0,0)',
      bottomFillColor2:'rgba(0,0,0,0)',
      priceLineVisible: false,
      lastValueVisible: false,
      lineWidth: 1,
    });
    var pts = candles.filter(function (c) { return c.time >= ob.from && c.time <= ob.to; })
                     .map(function (c) { return { time: c.time, value: ob.top }; });
    if (pts.length >= 2) series.setData(pts);
  });

  // ── Premium / Equilibrium / Discount zones (LuxAlgo 5% thin bands) ──
  if (pdZones) {
    var bands = [
      { z: pdZones.premium,     color: 'rgba(239, 71, 111, 0.45)', edge: 'rgba(239, 71, 111, 0.9)' },
      { z: pdZones.equilibrium, color: 'rgba(135, 139, 148, 0.30)', edge: 'rgba(135, 139, 148, 0.9)' },
      { z: pdZones.discount,    color: 'rgba(6, 214, 160, 0.45)',  edge: 'rgba(6, 214, 160, 0.9)' },
    ];
    bands.forEach(function (b) {
      var s = chart.addBaselineSeries({
        baseValue: { type: 'price', price: b.z.bottom },
        topLineColor: b.edge,
        topFillColor1: b.color,
        topFillColor2: b.color,
        bottomLineColor: 'rgba(0,0,0,0)',
        bottomFillColor1: 'rgba(0,0,0,0)',
        bottomFillColor2: 'rgba(0,0,0,0)',
        priceLineVisible: false,
        lastValueVisible: false,
        lineWidth: 1,
      });
      s.setData(candles.map(function (c) { return { time: c.time, value: b.z.top }; }));
    });
  }

  // ── Trendlines (upper down-slope, lower up-slope) ──
  if (tlUpper && tlUpper.length > 1) {
    var upper = chart.addLineSeries({
      color: '#fb7185', lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    upper.setData(tlUpper);
  }
  if (tlLower && tlLower.length > 1) {
    var lower = chart.addLineSeries({
      color: '#2dd4bf', lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    lower.setData(tlLower);
  }

  // ── candlesticks ──
  var candleSeries = chart.addCandlestickSeries({
    upColor:        '#06d6a0',
    downColor:      '#ef476f',
    borderUpColor:  '#06d6a0',
    borderDownColor:'#ef476f',
    wickUpColor:    '#06d6a0',
    wickDownColor:  '#ef476f',
  });
  candleSeries.setData(candles);

  if (markers && markers.length) {
    var t0 = candles[0].time;
    var tN = candles[candles.length - 1].time;
    var visible = markers
      .filter(function (m) { return m.time >= t0 && m.time <= tN; })
      .sort(function (a, b) { return a.time - b.time; });
    if (visible.length) candleSeries.setMarkers(visible);
  }

  // ── MTF horizontal price lines (PDH/PDL/PWH/PWL) ──
  if (mtf) {
    var lines = [
      { p: mtf.pdh, color: '#4cc9f0', title: 'PDH' },
      { p: mtf.pdl, color: '#4cc9f0', title: 'PDL' },
      { p: mtf.pwh, color: '#a78bfa', title: 'PWH' },
      { p: mtf.pwl, color: '#a78bfa', title: 'PWL' },
    ];
    lines.forEach(function (ln) {
      if (ln.p == null) return;
      candleSeries.createPriceLine({
        price: ln.p,
        color: ln.color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: ln.title,
      });
    });
  }

  chart.timeScale().fitContent();
  window.addEventListener('resize', function () {
    chart.applyOptions({ width: container.clientWidth });
  });
})();
</script>
</body>
</html>
""")


# ── public ────────────────────────────────────────────────────────────────────

def generate_html(
    signal: SMCSignal,
    daily_df: Optional[pd.DataFrame] = None,
    intraday_df: Optional[pd.DataFrame] = None,
    *,
    fallback_to_daily: bool = False,
) -> str:
    """Render a self-contained HTML SMC report with full LuxAlgo-style chart."""
    last_close = signal.meta.get("last_close", signal.price)
    pct = 0.0
    if daily_df is not None and len(daily_df) >= 2:
        prev = float(daily_df["close"].iloc[-2])
        if prev > 0:
            pct = (last_close / prev - 1.0) * 100

    daily_dir = "—"
    if daily_df is not None and len(daily_df) >= 5:
        d_close = float(daily_df["close"].iloc[-1])
        d_first = float(daily_df["close"].iloc[-5])
        if d_first > 0:
            chg = (d_close / d_first - 1.0) * 100
            daily_dir = f"近5日 {chg:+.2f}%"

    notice = ""
    if fallback_to_daily:
        notice = '<div class="notice">⚠ 分鐘線資料為空，已 fallback 為日線數據。</div>'

    rows_price = (
        _row("當前價", f"{last_close:.2f}")
        + _row("訊號價位", f"{signal.price:.2f}")
        + _row("日線變化", f"{pct:+.2f}%")
    )
    rows_struct = (
        _row("時間框架", escape(signal.timeframe))
        + _row("市場結構", escape(signal.market_structure))
        + _row("日線方向", escape(daily_dir))
    )
    rows_zones = (
        _row("Demand Zone", _fmt_zone(signal.demand_zone))
        + _row("Supply Zone", _fmt_zone(signal.supply_zone))
    )

    # Pick the frame the chart will render. Prefer intraday when present, else daily.
    if intraday_df is not None and not intraday_df.empty and len(intraday_df) >= 5:
        # 1m frames are dense — show more bars; tighter swing windows would
        # over-trigger on intraday noise, so widen them.
        if signal.timeframe == "1m":
            chart_df = intraday_df.tail(1400)   # ≈ 5 trading days @ 1m
            internal_n, swing_n = 5, 15
        else:
            chart_df = intraday_df.tail(90)
            internal_n, swing_n = 3, 8
    elif daily_df is not None and not daily_df.empty:
        chart_df = daily_df.tail(90)
        internal_n, swing_n = 5, 12
    else:
        chart_df = pd.DataFrame()
        internal_n, swing_n = 5, 10

    ctx = _build_chart_context(
        chart_df, internal_n=internal_n, swing_n=swing_n,
        daily_df=daily_df,
    )
    bars_shown = len(ctx["candles"])

    # Static PNG fallback — embedded as <img> so Telegram preview (JS-blocked)
    # still shows the chart. JS removes it when lightweight-charts loads.
    chart_fallback_img = ""
    if not chart_df.empty:
        try:
            # Wider canvas for 1m so 1000+ bars stay legible.
            figsize = (20, 7) if signal.timeframe == "1m" else (12, 6)
            png_bytes = render_chart_png(
                chart_df,
                signal=signal,
                internal_n=internal_n,
                swing_n=swing_n,
                figsize=figsize,
                daily_df=daily_df,
            )
            if png_bytes:
                chart_fallback_img = (
                    f'<img id="chart-fallback" alt="SMC chart" '
                    f'src="{_png_data_uri(png_bytes)}">'
                )
        except Exception as exc:
            logger.warning("PNG fallback render failed: %s", exc)

    # Swing high/low totals = count of swing markers / 2 ish; expose explicit
    sp_total = 0
    if not chart_df.empty:
        sp = find_swing_points(chart_df, n=swing_n)
        sp_total = len(sp.get("swing_highs", [])) + len(sp.get("swing_lows", []))

    sw = ctx.get("strong_weak", {})
    if sw.get("strong_high") and sw.get("weak_low"):
        sw_label = "BEAR"
    elif sw.get("weak_high") and sw.get("strong_low"):
        sw_label = "BULL"
    else:
        sw_label = "—"

    demand_payload = None
    if signal.demand_zone:
        demand_payload = {
            "top": float(signal.demand_zone["top"]),
            "bottom": float(signal.demand_zone["bottom"]),
        }
    supply_payload = None
    if signal.supply_zone:
        supply_payload = {
            "top": float(signal.supply_zone["top"]),
            "bottom": float(signal.supply_zone["bottom"]),
        }

    return _TEMPLATE.substitute(
        symbol=escape(signal.symbol),
        signal_type=escape(signal.signal_type),
        pill_class=_pill_class(signal.signal_type),
        ts=signal.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        timeframe=escape(signal.timeframe),
        notice=notice,
        strength=_stars(signal.strength),
        rows_price=rows_price,
        rows_struct=rows_struct,
        rows_zones=rows_zones,
        advice=escape(_advice(signal)),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        bars_shown=bars_shown,
        swing_count=sp_total,
        fvg_count=len([f for f in ctx["fvgs"] if f.get("valid")]),
        eq_count=ctx.get("eq_total", 0),
        sw_label=sw_label,
        candles_json=json.dumps(ctx["candles"], ensure_ascii=False),
        markers_json=json.dumps(ctx["markers"], ensure_ascii=False),
        fvgs_json=json.dumps(ctx["fvgs"], ensure_ascii=False),
        eq_lines_json=json.dumps(ctx["eq_lines"], ensure_ascii=False),
        demand_json=json.dumps(demand_payload, ensure_ascii=False),
        supply_json=json.dumps(supply_payload, ensure_ascii=False),
        order_blocks_json=json.dumps(ctx["order_blocks"], ensure_ascii=False),
        pd_zones_json=json.dumps(ctx["pd_zones"], ensure_ascii=False),
        tl_upper_json=json.dumps(ctx["trendlines_upper"], ensure_ascii=False),
        tl_lower_json=json.dumps(ctx["trendlines_lower"], ensure_ascii=False),
        mtf_json=json.dumps(ctx["mtf"], ensure_ascii=False),
        ob_count=ctx.get("ob_total", 0),
        tl_break_count=ctx.get("trendline_breaks_total", 0),
        chart_fallback_img=chart_fallback_img,
    )
