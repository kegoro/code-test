"""ATM × SMC 策略圖 — 在真實個股 K 線上疊策略標記，輸出 PNG。

對應策略規格：`ATM_SMC_策略.md` 第 5 節「生圖視覺規格」、LESSONS.md §2.14。

疊加元素：時段高低線 H1/L1、Order Block 需求區、進場/停損/目標線、
收針確認標記、型態與 R:R 資訊框。台股慣例上色（紅漲綠跌）。

用法：
    python -m backend.strategy_chart 2330                # 真實當日 M3（需 Shioaji 登入）
    python -m backend.strategy_chart 2330 --date 2026-06-10
    python -m backend.strategy_chart DEMO --demo         # 離線合成資料測試
    python -m backend.strategy_chart 2330 --csv bars.csv # 從 CSV 讀 M3

進出場價語意沿用 `n_pattern.py`：進場=OB 上緣、停損=OB 下緣、保守目標=H1，
另疊 1:3 目標線（ATM 補充）。本工具純讀資料 + 畫圖，不下單、不改訊號程式。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import date as date_cls
from io import BytesIO
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # headless：只輸出 PNG，不開視窗
import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

logger = logging.getLogger("strategy-chart")

# 繁中字型（Windows 內建微軟正黑體）；缺字型會變成方塊豆腐
plt.rcParams["font.sans-serif"] = [
    "Microsoft JhengHei", "Microsoft YaHei", "SimHei", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

_MIN_BARS = 10
_BEAT1_MIN_PCT = 2.0  # 與 n_pattern.py 一致：第一拍至少 +2%

# 語意配色（避開台股紅綠 K 棒，用橘/藍/紫讓標記跳出來）
_C_OB = "#ff9800"
_C_OB_EDGE = "#e65100"
_C_ENTRY = "#1565c0"
_C_STOP = "#8e24aa"
_C_TARGET = "#00897b"
_C_SESSION = "#9e9e9e"
_C_WICK_OK = "#e65100"
_C_WICK_NO = "#c62828"


@dataclass(frozen=True)
class StrategyLevels:
    """一張策略圖要畫的所有關鍵價位與索引。"""

    direction: str          # "long"
    pattern: str            # "連續型" / "反轉型"
    open_px: float
    h1: float
    h1_idx: int
    l1: float
    l1_idx: int
    ob_bottom: float
    ob_top: float
    ob_idx: int
    entry: float
    stop: float
    target: float           # 保守目標 = H1
    target_rr3: float       # ATM 1:3 目標
    rr: float               # H1 目標的 R:R
    wick_idx: int
    wick_confirmed: bool
    ob_source: str          # "detector" | "approx"
    note: str


# ── 等級計算（沿用 N 字幾何） ────────────────────────────────────────────

def _find_bullish_ob(active_obs, l1: float) -> Optional[tuple[float, float]]:
    """從偵測器的 active_obs 找出包住 L1 的 bullish OB。"""
    if not active_obs:
        return None
    for o in active_obs:
        if o.get("bias") == "bullish" and o["bottom"] <= l1 <= o["top"]:
            return float(o["bottom"]), float(o["top"])
    return None


def _approx_ob(
    opens, highs, lows, closes, l1_idx: int
) -> tuple[float, float, int]:
    """偵測器沒給 OB 時，用「反彈前最後一根空方 K」近似需求區（經典 OB 定義）。"""
    for i in range(l1_idx, -1, -1):
        if closes[i] < opens[i]:  # 最後一根 bearish K
            return float(lows[i]), float(highs[i]), i
    return float(lows[l1_idx]), float(highs[l1_idx]), l1_idx


def _is_wick_rejection(opens, highs, lows, closes, idx: int, ob_bottom: float) -> bool:
    """收針判定：下影線 ≥ 實體、收盤未破 OB 下緣（ATM_SMC_策略.md §3.3）。"""
    body = abs(float(closes[idx]) - float(opens[idx]))
    lower_wick = min(float(opens[idx]), float(closes[idx])) - float(lows[idx])
    return lower_wick >= max(body, 1e-9) and float(closes[idx]) >= ob_bottom


def compute_levels(m3: pd.DataFrame, active_obs=None) -> Optional[StrategyLevels]:
    """從 M3 K 線算出 N 字 / ATM 的時段高低、OB、進出場價。

    永遠盡量回傳可畫的結構（即使不是教科書 N 字），note 標明品質。
    """
    if m3 is None or len(m3) < _MIN_BARS:
        return None

    opens = m3["open"].astype(float).to_numpy()
    highs = m3["high"].astype(float).to_numpy()
    lows = m3["low"].astype(float).to_numpy()
    closes = m3["close"].astype(float).to_numpy()
    n = len(m3)

    open_px = float(opens[0])
    if open_px <= 0:
        return None

    h1_idx = int(highs.argmax())
    h1 = float(highs[h1_idx])
    first_pct = (h1 - open_px) / open_px * 100.0

    # H1 之後的最低點 = 回踩低 L1
    if h1_idx >= n - 1:
        l1_idx, l1 = h1_idx, h1
    else:
        post_lows = lows[h1_idx + 1:]
        l1_local = int(post_lows.argmin())
        l1_idx = h1_idx + 1 + l1_local
        l1 = float(lows[l1_idx])

    detector_ob = _find_bullish_ob(active_obs, l1)
    if detector_ob is not None:
        ob_bottom, ob_top = detector_ob
        ob_idx = l1_idx
        ob_source = "detector"
    else:
        ob_bottom, ob_top, ob_idx = _approx_ob(opens, highs, lows, closes, l1_idx)
        ob_source = "approx"

    entry = round(ob_top, 2)
    stop = round(ob_bottom, 2)
    target = round(h1, 2)
    risk = max(entry - stop, 1e-9)
    target_rr3 = round(entry + 3.0 * risk, 2)
    rr = round((target - entry) / risk, 2)

    confirmed = _is_wick_rejection(opens, highs, lows, closes, l1_idx, ob_bottom)

    if first_pct >= _BEAT1_MIN_PCT and h1_idx < n - 2 and l1_idx < n - 1:
        note = f"N 字結構成立（第一拍 +{first_pct:.1f}%）"
    else:
        note = f"結構未完整（第一拍 +{first_pct:.1f}%，僅供觀察）"

    return StrategyLevels(
        direction="long",
        pattern="連續型",
        open_px=open_px,
        h1=h1, h1_idx=h1_idx,
        l1=l1, l1_idx=l1_idx,
        ob_bottom=ob_bottom, ob_top=ob_top, ob_idx=ob_idx,
        entry=entry, stop=stop, target=target, target_rr3=target_rr3, rr=rr,
        wick_idx=l1_idx, wick_confirmed=confirmed,
        ob_source=ob_source, note=note,
    )


# ── 繪圖 ──────────────────────────────────────────────────────────────────

def _tw_style():
    """台股慣例：紅漲綠跌。"""
    mc = mpf.make_marketcolors(
        up="#d62728", down="#2ca02c", edge="inherit", wick="inherit"
    )
    return mpf.make_mpf_style(
        marketcolors=mc, gridstyle=":", facecolor="white",
        rc={"font.sans-serif": plt.rcParams["font.sans-serif"]},
    )


def _draw_figure(
    symbol: str, m3: pd.DataFrame, levels: StrategyLevels, *, date_label: str = "",
):
    """畫 M3 蠟燭圖並疊上策略標記，回傳 matplotlib figure。"""
    df = m3.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    if "Volume" not in df.columns:
        df["Volume"] = 0.0

    fig, axes = mpf.plot(
        df, type="candle", style=_tw_style(), returnfig=True,
        figsize=(12, 7), volume=False, ylabel="價格",
        datetime_format="%H:%M", xrotation=0, tight_layout=True,
    )
    ax = axes[0]
    n = len(df)
    x_right = n - 1
    ax.set_xlim(-1, x_right + max(7.0, n * 0.16))  # 右側留白給標籤
    lx = x_right + 1.2  # 標籤 x 位置

    # OB 需求區（從形成處延伸到右緣）
    ax.add_patch(Rectangle(
        (levels.ob_idx - 0.5, levels.ob_bottom),
        x_right - levels.ob_idx + 1.0, levels.ob_top - levels.ob_bottom,
        facecolor=_C_OB, alpha=0.16, edgecolor=_C_OB_EDGE, lw=1.0, zorder=0,
    ))
    ob_tag = "OB 需求區" + ("" if levels.ob_source == "detector" else "（近似）")
    ax.text(levels.ob_idx, levels.ob_top, ob_tag, fontsize=8,
            color=_C_OB_EDGE, va="bottom")

    # L1 時段低線
    ax.hlines(levels.l1, 0, x_right, colors=_C_SESSION, linestyles=":", lw=1.0)
    ax.text(lx, levels.l1, f"L1 {levels.l1:.2f}", va="center", fontsize=8, color="#555")

    # H1：保守目標常 = H1，同價時合併標示避免重疊
    if abs(levels.target - levels.h1) < 0.01:
        ax.hlines(levels.h1, 0, x_right, colors=_C_TARGET, linestyles="--", lw=1.3)
        ax.text(lx, levels.h1, f"H1／目標 {levels.h1:.2f}（1:{levels.rr:.1f}）",
                va="center", fontsize=9, color=_C_TARGET)
    else:
        ax.hlines(levels.h1, 0, x_right, colors=_C_SESSION, linestyles=":", lw=1.0)
        ax.text(lx, levels.h1, f"H1 {levels.h1:.2f}", va="center", fontsize=8, color="#555")
        ax.hlines(levels.target, 0, x_right, colors=_C_TARGET, linestyles="--", lw=1.3)
        ax.text(lx, levels.target, f"目標 {levels.target:.2f}（1:{levels.rr:.1f}）",
                va="center", fontsize=9, color=_C_TARGET)

    # 進場 / 停損
    ax.hlines(levels.entry, 0, x_right, colors=_C_ENTRY, linestyles="--", lw=1.3)
    ax.text(lx, levels.entry, f"進場 {levels.entry:.2f}", va="center",
            fontsize=9, color=_C_ENTRY)
    ax.hlines(levels.stop, 0, x_right, colors=_C_STOP, linestyles="--", lw=1.3)
    ax.text(lx, levels.stop, f"停損 {levels.stop:.2f}", va="center",
            fontsize=9, color=_C_STOP)

    # 1:3 目標（ATM 補充）
    ax.hlines(levels.target_rr3, 0, x_right, colors=_C_TARGET, linestyles=":", lw=1.1)
    ax.text(lx, levels.target_rr3, f"1:3 目標 {levels.target_rr3:.2f}", va="center",
            fontsize=8, color=_C_TARGET)

    # 收針標記
    wick_ok = levels.wick_confirmed
    span = max(levels.h1 - levels.l1, levels.l1 * 0.01)
    ax.annotate(
        "收針確認" if wick_ok else "無收針",
        xy=(levels.wick_idx, levels.l1),
        xytext=(levels.wick_idx, levels.l1 - span * 0.18),
        ha="center", fontsize=9, color=_C_WICK_OK if wick_ok else _C_WICK_NO,
        arrowprops=dict(arrowstyle="->", color=_C_WICK_OK if wick_ok else _C_WICK_NO),
    )

    # 左上資訊框
    info = (
        f"{levels.pattern}・{'做多' if levels.direction == 'long' else '做空'}\n"
        f"進場 {levels.entry:.2f} / 停損 {levels.stop:.2f} / 目標 {levels.target:.2f}\n"
        f"R:R 1:{levels.rr:.1f}　(1:3→{levels.target_rr3:.2f})\n"
        f"收針：{'有' if wick_ok else '無'}　"
        f"OB：{'偵測' if levels.ob_source == 'detector' else '近似'}\n"
        f"{levels.note}"
    )
    ax.text(0.012, 0.985, info, transform=ax.transAxes, va="top", ha="left",
            fontsize=9, bbox=dict(boxstyle="round", facecolor="white",
                                  edgecolor="#cccccc", alpha=0.92))

    ax.set_title(f"{symbol}　ATM×SMC 策略圖　{date_label}".strip(),
                 fontsize=13, fontweight="bold")
    return fig


def render_strategy_chart(
    symbol: str, m3: pd.DataFrame, levels: StrategyLevels, *,
    out_path: str, date_label: str = "",
) -> str:
    """畫圖並存成 PNG 檔，回傳路徑（CLI 用）。"""
    fig = _draw_figure(symbol, m3, levels, date_label=date_label)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info("策略圖已輸出：%s", out_path)
    return out_path


def build_chart_png(
    symbol: str, m3: pd.DataFrame, levels: StrategyLevels, *, date_label: str = "",
) -> bytes:
    """畫圖並回傳 PNG bytes（Telegram 直接送、不落地）。"""
    fig = _draw_figure(symbol, m3, levels, date_label=date_label)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ── 資料來源 ────────────────────────────────────────────────────────────

def _demo_m3() -> pd.DataFrame:
    """合成一段乾淨的 N 字（含收針），供離線測試畫圖。"""
    idx = pd.date_range("2026-06-10 09:00", periods=40, freq="3min")
    # 收盤路徑：100→105(H1)→101.8(L1, 收針)→103.8
    close_path = (
        [100.0, 100.6, 101.4, 102.3, 103.1, 103.9, 104.5, 104.9, 105.0]  # 第一拍
        + [104.6, 104.1, 103.5, 103.0, 102.6, 102.3, 102.0, 102.6]        # 回踩+收針(idx16)
        + [103.0, 103.3, 103.5, 103.6, 103.7, 103.8] + [103.8] * 17       # 反彈
    )
    rows = []
    prev = 100.0
    for i, c in enumerate(close_path):
        o = prev
        hi = max(o, c) + 0.15
        lo = min(o, c) - 0.15
        if i == 16:  # 收針那根：長下影線
            o, c = 102.3, 102.6
            lo = 101.5
            hi = 102.7
        rows.append((o, hi, lo, c, 1000 + i * 10))
        prev = c
    return pd.DataFrame(
        rows, index=idx, columns=["open", "high", "low", "close", "volume"]
    )


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    return df


async def _load_live(symbol: str, day: str | None):
    """真實當日資料：gather_context 給真實 OB；指定日期則用 shioaji_fetch_m3。"""
    if day is None:
        from backend.smc_analyst.context import gather_context
        from backend.smc_analyst.setups.n_pattern import _resample_to_3m_today
        ctx = await gather_context(symbol)
        m3 = _resample_to_3m_today(ctx.ltf.bars, ctx.now_tw.date())
        return m3, ctx.active_obs
    from backend.shioaji_fetcher import shioaji_fetch_m3
    m3 = await shioaji_fetch_m3(symbol, day)
    return m3, None


async def generate_chart_png(
    symbol: str, day: str | None = None
) -> tuple[bytes, str]:
    """高階 API（給 Telegram /chart）：抓真實當日資料 → 算 levels → 回 (png_bytes, 日期標籤)。

    day=None 用今日（gather_context 真實 OB）；指定日期用 shioaji_fetch_m3。
    資料不足 / 算不出結構時 raise ValueError（caller 用 _safe_err 包）。
    """
    m3, active_obs = await _load_live(symbol, day)
    if m3 is None or len(m3) < _MIN_BARS:
        got = 0 if m3 is None else len(m3)
        raise ValueError(
            f"{symbol} 當日 M3 不足（需 ≥{_MIN_BARS} 根、目前 {got} 根）；"
            "開盤未滿 30 分鐘或非交易日會這樣"
        )
    levels = compute_levels(m3, active_obs)
    if levels is None:
        raise ValueError(f"{symbol} 無法從當日資料算出策略結構")
    date_label = day or str(date_cls.today())
    png = await asyncio.to_thread(
        build_chart_png, symbol, m3, levels, date_label=date_label
    )
    return png, date_label


def _safe_name(symbol: str) -> str:
    return "".join(ch for ch in symbol if ch.isalnum()) or "chart"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="ATM×SMC 策略圖生成器")
    p.add_argument("symbol", help="股號，例如 2330（--demo 時可隨意）")
    p.add_argument("--demo", action="store_true", help="用合成資料離線測試")
    p.add_argument("--csv", help="從 CSV 讀 M3（欄位 open/high/low/close/volume）")
    p.add_argument("--date", help="指定日期 YYYY-MM-DD（用 shioaji_fetch_m3）")
    p.add_argument("--out", help="輸出 PNG 路徑")
    args = p.parse_args()

    if args.demo:
        m3, active_obs = _demo_m3(), None
        date_label = "2026-06-10（示範資料）"
    elif args.csv:
        m3, active_obs = _load_csv(args.csv), None
        date_label = args.date or ""
    else:
        try:
            m3, active_obs = asyncio.run(_load_live(args.symbol, args.date))
        except Exception as exc:  # noqa: BLE001 — CLI 友善訊息
            logger.error("拉取 %s 資料失敗：%s", args.symbol, exc)
            logger.error("提示：需 Shioaji 登入 + IP 白名單（LESSONS §2.11）；"
                         "離線測試請加 --demo")
            raise SystemExit(1)
        date_label = args.date or str(date_cls.today())

    if m3 is None or len(m3) < _MIN_BARS:
        logger.error("資料不足（需 ≥ %d 根 M3），拿到 %s 根",
                     _MIN_BARS, 0 if m3 is None else len(m3))
        raise SystemExit(1)

    levels = compute_levels(m3, active_obs)
    if levels is None:
        logger.error("無法從資料算出策略結構")
        raise SystemExit(1)

    out = args.out or f"strategy_chart_{_safe_name(args.symbol)}_{date_label or 'now'}.png"
    render_strategy_chart(args.symbol, m3, levels, out_path=out, date_label=date_label)
    logger.info("完成：%s", out)


if __name__ == "__main__":
    main()
