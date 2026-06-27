"""潛力股掃描器 — 依「6 條技術特性」對中大型活躍股計分排名。

供 smc_bot `/potential` 指令用。資料源 Shioaji（還原日線，複用 smc_bot 已登入連線，
不另開 session 以免撞 451 Too Many Connections）。涵蓋上市(TSE)+上櫃(OTC)。

6 條（出自使用者選股總結圖 IMG_7051），量化判定：
  ① 量放大        : 今日量 ≥ VOL_MULT × 20日均量
  ② 均線多頭      : MA20 上彎(今 > 5日前) 且 收盤 > MA20
  ③ 布林開口      : 帶寬(上-下)/中軌 比 5 日前放大 且 收盤 > 中軌
  ④ 斐波回調      : 近 FIB_LOOKBACK 日「低→高」波段，回調落在 38.2%~61.8%(含容差)
  ⑤ RSI 止穩翻揚  : RSI(14) 在 45~60 且 今天 > 昨天
  ⑥ MACD 金叉     : 近 3 日內 DIF 上穿 DEA(柱由負翻正)

6 條互斥（③突破 vs ④拉回不會同日成立）故用「計分 0–6」非 AND；
中越多越接近發動：中④=拉回找買點型、中⑥=已啟動追勢型。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.shioaji_fetcher import (
    _get_api,
    _sync_fetch_daily,
    _SNAPSHOT_BATCH,
)

# ── 判定參數（要調篩選嚴格度改這裡）──────────────────────────────────────────
VOL_MULT = 1.5            # ① 量能倍數
MA_PERIOD = 20           # ②③ 均線/布林週期
SLOPE_LOOKBACK = 5       # ② 均線上彎比較天數
BAND_LOOKBACK = 5        # ③ 布林開口比較天數
BAND_OPEN_RATIO = 1.05   # ③ 帶寬至少放大 5%
FIB_LOOKBACK = 60        # ④ 找波段的回看天數
FIB_LOW, FIB_HIGH = 0.382, 0.618
FIB_TOL = 0.05           # ④ 斐波區間容差
RSI_PERIOD = 14
RSI_LOW, RSI_HIGH = 45.0, 60.0   # ⑤ RSI 止穩帶
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
CROSS_WINDOW = 3         # ⑥ 金叉回看天數
MIN_BARS = FIB_LOOKBACK + 5
DAILY_LOOKBACK = 120     # 抓日線根數（夠 60 日波段 + MA20 + MACD 暖機）
DEEP_LIMIT = 150         # 中大型活躍股：依今日成交值排序，只深掃前 N 檔
DEFAULT_MIN_SCORE = 4

COND_MARK = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}


@dataclass(frozen=True)
class PotentialCandidate:
    code: str
    name: str
    trade_value: float       # 今日成交值（close×量），活躍度排序用
    close: float
    score: int
    conds: tuple[int, ...]
    rsi: float
    fib_retr: float          # 回調比例（NaN=無有效波段）
    vol_ratio: float         # 今日量 / 20日均量


@dataclass(frozen=True)
class PotentialResult:
    candidates: tuple[PotentialCandidate, ...]  # 依 (score, trade_value) 排序
    scanned: int            # snapshot 報價成功數
    deep_analyzed: int      # 實際深度分析檔數
    min_score: int


_MARKET_CLOSE = dtime(13, 35)   # 台股 13:30 收盤 + 緩衝


def _market_closed_now() -> bool:
    """當前是否已過今日收盤（含週末視為已收，最後一根即完整日線）。"""
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    if now.weekday() >= 5:
        return True
    return now.time() >= _MARKET_CLOSE


def _trim_forming(df: pd.DataFrame) -> pd.DataFrame:
    """盤中時剔除「今天形成中的半根 K」→ 只用已收完的日線評分（潛力股本質是收盤級篩選）。"""
    if df.empty or _market_closed_now():
        return df
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    if df.index[-1].date() == today:
        return df.iloc[:-1]
    return df


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def _score_df(df: pd.DataFrame) -> tuple[int, list[int], float, float, float]:
    """回傳 (score, 命中條件list, 最新RSI, 斐波回調比例, 量比)。資料不足回 (0,[],nan,nan,0)。"""
    if df.empty or len(df) < MIN_BARS:
        return 0, [], float("nan"), float("nan"), 0.0
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    conds: list[int] = []

    # ① 量放大
    vol_ma = vol.rolling(MA_PERIOD).mean()
    vol_ratio = float(vol.iloc[-1] / vol_ma.iloc[-1]) if vol_ma.iloc[-1] > 0 else 0.0
    if vol_ratio >= VOL_MULT:
        conds.append(1)

    # ② 均線多頭
    ma = close.rolling(MA_PERIOD).mean()
    if ma.iloc[-1] > ma.iloc[-1 - SLOPE_LOOKBACK] and close.iloc[-1] > ma.iloc[-1]:
        conds.append(2)

    # ③ 布林開口：帶寬 (上-下)/中 = 4σ/MA
    std = close.rolling(MA_PERIOD).std()
    bandwidth = (4 * std) / ma
    if bandwidth.iloc[-1] > bandwidth.iloc[-1 - BAND_LOOKBACK] * BAND_OPEN_RATIO and close.iloc[-1] > ma.iloc[-1]:
        conds.append(3)

    # ④ 斐波回調：近 FIB_LOOKBACK 找最低，其後最高，回調比例
    window = df.iloc[-FIB_LOOKBACK:]
    low_idx = window["low"].idxmin()
    after = window.loc[low_idx:]
    fib_retr = float("nan")
    if len(after) >= 2:
        swing_low = float(window["low"].min())
        swing_high = float(after["high"].max())
        if swing_high > swing_low:
            fib_retr = (swing_high - close.iloc[-1]) / (swing_high - swing_low)
            if FIB_LOW - FIB_TOL <= fib_retr <= FIB_HIGH + FIB_TOL:
                conds.append(4)

    # ⑤ RSI 止穩翻揚
    rsi = _rsi(close)
    if RSI_LOW <= rsi.iloc[-1] <= RSI_HIGH and rsi.iloc[-1] > rsi.iloc[-2]:
        conds.append(5)

    # ⑥ MACD 金叉（近 CROSS_WINDOW 日柱由負翻正）
    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = dif - dea
    if hist.iloc[-1] > 0 and hist.iloc[-1 - CROSS_WINDOW] < 0:
        conds.append(6)

    return len(conds), conds, float(rsi.iloc[-1]), fib_retr, vol_ratio


def _active_contracts(api) -> list:
    """上市(TSE)+上櫃(OTC) 普通股：4 碼純數字、首碼非 0（排除 ETF/權證/特別股）。"""
    out = []
    for board in (api.Contracts.Stocks.TSE, api.Contracts.Stocks.OTC):
        for c in board:
            code = getattr(c, "code", "") or ""
            if len(code) == 4 and code.isdigit() and code[0] != "0":
                out.append(c)
    return out


def _sync_scan(min_score: int) -> PotentialResult:
    api = _get_api()
    contracts = _active_contracts(api)
    by_code = {c.code: c for c in contracts}

    scanned = 0
    raw: list[tuple[str, float, float]] = []  # (code, close, trade_value)
    for i in range(0, len(contracts), _SNAPSHOT_BATCH):
        try:
            snaps = api.snapshots(contracts[i:i + _SNAPSHOT_BATCH])
        except Exception:
            continue
        for s in snaps or []:
            vol = int(getattr(s, "total_volume", 0) or 0)
            if vol <= 0:
                continue
            scanned += 1
            close = float(getattr(s, "close", 0.0) or 0.0)
            raw.append((str(getattr(s, "code", "")), close, close * vol))

    # 中大型活躍股：依今日成交值排序，只深掃前 DEEP_LIMIT 檔
    raw.sort(key=lambda x: x[2], reverse=True)
    deep = raw[:DEEP_LIMIT]
    survivors: list[PotentialCandidate] = []
    for code, close, tv in deep:
        try:
            df = _trim_forming(_sync_fetch_daily(code, DAILY_LOOKBACK))
            score, conds, rsi, fib, vr = _score_df(df)
        except Exception:
            continue
        if score >= min_score:
            survivors.append(PotentialCandidate(
                code=code, name=(getattr(by_code.get(code), "name", "") or code),
                trade_value=tv, close=float(df["close"].iloc[-1]),  # 評分那根的收盤(剔半根後)
                score=score, conds=tuple(conds), rsi=rsi, fib_retr=fib, vol_ratio=vr,
            ))

    survivors.sort(key=lambda c: (c.score, c.trade_value), reverse=True)
    return PotentialResult(
        candidates=tuple(survivors), scanned=scanned,
        deep_analyzed=len(deep), min_score=min_score,
    )


async def scan(min_score: int = DEFAULT_MIN_SCORE) -> PotentialResult:
    """跑潛力股 6 條件掃描（snapshot 取活躍股 + 逐檔日線計分）。在 thread 執行不阻塞 event loop。"""
    return await asyncio.to_thread(_sync_scan, min_score)
