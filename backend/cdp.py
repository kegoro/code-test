"""CDP 逆勢操作系統 — 由「前一交易日」高/低/收算出四條當沖輔助線。

四線(標準版):
    CDP      = (前日高 + 前日低 + 前日收) / 3
    AH 突破  = CDP + (前日高 − 前日低)
    NH 轉強  = 2×CDP − 前日低
    NL 轉弱  = 2×CDP − 前日高
    AL 跌破  = CDP − (前日高 − 前日低)

應用規則(雷老闆給定):
    1. 開盤≈AH → 追價買進;開盤≈AL → 放空。
    2. 盤中接近 NH → 賣出點;接近 NL → 買進點。
    3. 開盤直接穿越 NH/NL → 趨勢盤較有利;開在 NH~NL 間 → 當沖較無利,觀望。
    4. 盤中穿越 AH/AL → 追買 / 加空參考。

資料源:台股走 shioaji(日線+今日 m1 即時開盤/現價),美股走 yfinance。
CLI 快測: python -m backend.cdp 2330 AAPL
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("cdp")

_TZ_TW = ZoneInfo("Asia/Taipei")
_TZ_US = ZoneInfo("America/New_York")

# 「接近某線」判定:價格落在該線 ±(前日振幅 × 此比例) 內視為靠近
NEAR_TOL_FRAC = 0.20


@dataclass(frozen=True)
class CDPLevels:
    prev_high: float
    prev_low: float
    prev_close: float
    cdp: float
    ah: float
    nh: float
    nl: float
    al: float
    prev_date: str = ""


def is_us(symbol: str) -> bool:
    """含英文字母 = 美股 ticker(台股代號純數字)。"""
    return any(ch.isalpha() for ch in symbol)


def compute_cdp(prev_high: float, prev_low: float, prev_close: float,
                *, prev_date: str = "") -> CDPLevels:
    """由前一交易日 HLC 算出 CDP 四線。"""
    cdp = (prev_high + prev_low + prev_close) / 3
    rng = prev_high - prev_low
    return CDPLevels(
        prev_high=prev_high, prev_low=prev_low, prev_close=prev_close,
        cdp=cdp,
        ah=cdp + rng,
        nh=2 * cdp - prev_low,
        nl=2 * cdp - prev_high,
        al=cdp - rng,
        prev_date=prev_date,
    )


def cdp_signal(lv: CDPLevels, open_p: Optional[float],
               last_p: Optional[float]) -> list[str]:
    """套用四條規則,回傳建議文字(可能多行)。open/last 缺值時降級提示。"""
    rng = lv.prev_high - lv.prev_low
    tol = rng * NEAR_TOL_FRAC if rng > 0 else abs(lv.cdp) * 0.002

    if open_p is None:
        return ["尚無今日開盤價(美股非交易時段 / 台股盤前)。開盤後對照:"
                "開在 AH 追多、開在 AL 放空、開在 NH~NL 間多空不明則觀望。"]

    def near(a: float, b: float) -> bool:
        return abs(a - b) <= tol

    out: list[str] = []

    # ── 規則 1 + 3:用開盤價定位 ──
    if open_p >= lv.ah or near(open_p, lv.ah):
        out.append(f"開盤≈突破點 AH({_fmt(lv.ah)}):站穩可追價【做多】,失守即假突破。")
    elif open_p <= lv.al or near(open_p, lv.al):
        out.append(f"開盤≈跌破點 AL({_fmt(lv.al)}):弱勢可【放空】,拉回站上才解除。")
    elif open_p > lv.nh:
        out.append(f"開盤穿越轉強 NH({_fmt(lv.nh)}):趨勢偏【多】,較有利可圖,回測 NH 不破續抱。")
    elif open_p < lv.nl:
        out.append(f"開盤穿越轉弱 NL({_fmt(lv.nl)}):趨勢偏【空】,較有利可圖,反彈不過 NL 續空。")
    else:
        out.append(f"開盤落在 NH~NL 之間({_fmt(lv.nl)}~{_fmt(lv.nh)}):盤整,當沖較無利,"
                   "宜觀望;近 NH 偏空、近 NL 偏多做區間。")

    # ── 規則 2 + 4:用盤中現價給動作 ──
    if last_p is not None:
        if near(last_p, lv.nh):
            out.append(f"現價接近轉強 NH({_fmt(lv.nh)}):區間【賣出 / 減多】參考點。")
        elif near(last_p, lv.nl):
            out.append(f"現價接近轉弱 NL({_fmt(lv.nl)}):區間【買進 / 回補】參考點。")
        if last_p > lv.ah and open_p <= lv.ah:
            out.append(f"盤中向上穿越 AH({_fmt(lv.ah)}):可作【追買 / 加多】參考。")
        elif last_p < lv.al and open_p >= lv.al:
            out.append(f"盤中向下穿越 AL({_fmt(lv.al)}):可作【加空】參考。")

    return out


# 畫線用色票(對齊前端 index.html:--bad 紅 / --good 綠 / --muted 灰)
_LINE_COLOR_BREAK = "#ef476f"   # AH / NL(突破、轉弱 → 紅)
_LINE_COLOR_TREND = "#06d6a0"   # NH / AL(轉強、跌破 → 綠)
_LINE_COLOR_MID = "#7c8aa6"     # CDP 中軸(灰)


def levels_payload(lv: CDPLevels) -> list[dict]:
    """把 CDPLevels 攤成畫線用的 [{key,label,price,color}, ...](由上而下)。"""
    return [
        {"key": "AH", "label": "突破 AH", "price": lv.ah, "color": _LINE_COLOR_BREAK},
        {"key": "NH", "label": "轉強 NH", "price": lv.nh, "color": _LINE_COLOR_TREND},
        {"key": "CDP", "label": "CDP", "price": lv.cdp, "color": _LINE_COLOR_MID},
        {"key": "NL", "label": "轉弱 NL", "price": lv.nl, "color": _LINE_COLOR_BREAK},
        {"key": "AL", "label": "跌破 AL", "price": lv.al, "color": _LINE_COLOR_TREND},
    ]


def _fmt(x: float) -> str:
    return f"{x:,.2f}"


def _format(symbol: str, lv: CDPLevels,
            open_p: Optional[float], last_p: Optional[float]) -> str:
    head = f"前日{('(' + lv.prev_date + ')') if lv.prev_date else ''} " \
           f"高 {_fmt(lv.prev_high)} 低 {_fmt(lv.prev_low)} 收 {_fmt(lv.prev_close)}"
    lines = [
        f"📐 {symbol} CDP 逆勢操作",
        head,
        "",
        f"🔺 突破 AH  {_fmt(lv.ah)}",
        f"🟢 轉強 NH  {_fmt(lv.nh)}",
        f"·  CDP      {_fmt(lv.cdp)}",
        f"🔴 轉弱 NL  {_fmt(lv.nl)}",
        f"🔻 跌破 AL  {_fmt(lv.al)}",
    ]
    if open_p is not None:
        cur = f"今開 {_fmt(open_p)}"
        if last_p is not None:
            cur += f" | 現價 {_fmt(last_p)}"
        lines += ["", cur]
    lines += [""] + [f"👉 {s}" for s in cdp_signal(lv, open_p, last_p)]
    return "\n".join(lines)


# ── 取數(台股 shioaji / 美股 yfinance) ─────────────────────────────────────

class CDPDataError(Exception):
    """CDP 取數失敗(代號錯誤 / 查無日線)。"""


async def fetch_levels(
    symbol: str,
) -> tuple[CDPLevels, Optional[float], Optional[float]]:
    """取單一標的的 CDP 四線 + 今日開盤/現價(盤中才有)。

    回傳 (CDPLevels, open_p, last_p)。取數失敗時 raise CDPDataError。
    這是 analyze()(文字輸出)與圖表畫線端點共用的取數入口。
    """
    symbol = symbol.strip()
    if is_us(symbol):
        return await asyncio.to_thread(_levels_us, symbol.upper())
    return await _levels_tw(symbol)


async def get_levels(symbol: str) -> CDPLevels:
    """只回 CDP 四線,供圖表畫線用(不需要開盤/現價)。失敗 raise CDPDataError。"""
    lv, _, _ = await fetch_levels(symbol)
    return lv


async def analyze(symbol: str) -> str:
    """查單一標的 CDP,回傳可直接推 Telegram 的訊息。"""
    symbol = symbol.strip()
    try:
        lv, open_p, last_p = await fetch_levels(symbol)
    except CDPDataError as exc:
        return f"📐 {symbol}:CDP 取資料失敗({exc})。"
    return _format(symbol, lv, open_p, last_p)


def _levels_us(symbol: str) -> tuple[CDPLevels, Optional[float], Optional[float]]:
    from backend.diamond_blade3 import _fetch_us_daily

    rows = _fetch_us_daily(symbol, 15)
    if len(rows) < 2:
        raise CDPDataError("代號錯誤或查無日線")
    today = datetime.now(_TZ_US).date().isoformat()
    if rows[-1]["date"] == today:
        prev, today_bar = rows[-2], rows[-1]
        open_p, last_p = today_bar["open"], today_bar["close"]
    else:
        prev, open_p, last_p = rows[-1], None, None
    lv = compute_cdp(prev["max"], prev["min"], prev["close"], prev_date=prev["date"])
    return lv, open_p, last_p


async def _levels_tw(symbol: str) -> tuple[CDPLevels, Optional[float], Optional[float]]:
    from backend.shioaji_fetcher import shioaji_fetch_daily, shioaji_fetch_m1

    daily = await shioaji_fetch_daily(symbol, lookback=12)
    if daily is None or daily.empty or len(daily) < 1:
        raise CDPDataError("查無日線")

    today = datetime.now(_TZ_TW).date()
    prior = daily[daily.index.date < today]
    prev_row = prior.iloc[-1] if not prior.empty else daily.iloc[-1]
    try:
        prev_date = prev_row.name.date().isoformat()
    except AttributeError:
        prev_date = ""
    lv = compute_cdp(float(prev_row["high"]), float(prev_row["low"]),
                     float(prev_row["close"]), prev_date=prev_date)

    # 今日開盤 / 現價(盤中才有);best-effort,失敗不影響四線
    open_p = last_p = None
    try:
        m1 = await shioaji_fetch_m1(symbol, days=1)
        if m1 is not None and not m1.empty:
            td = m1[m1.index.date == today]
            if not td.empty:
                open_p = float(td["open"].iloc[0])
                last_p = float(td["close"].iloc[-1])
    except Exception as exc:
        logger.warning("cdp tw m1 %s: %s", symbol, exc)

    return lv, open_p, last_p


if __name__ == "__main__":
    import sys

    async def _main() -> None:
        syms = sys.argv[1:] or ["2330"]
        for s in syms:
            print(await analyze(s))
            print("-" * 40)

    asyncio.run(_main())
