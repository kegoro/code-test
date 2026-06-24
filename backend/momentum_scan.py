"""當沖選股篩選器 — 把使用者交易紀律程式化（LESSONS §2.12, 2026-06-09）。

供 smc_bot `/scan` 指令用。盤中即時，資料源 Shioaji（只需 Data 權限）。

紀律 → 實作：
  1 大盤環境   → 全市場上漲家數占比（breadth），soft gate（標示適不適合、不硬擋）
  2 漲幅 ≥ 5%  → snapshot change_rate（硬篩）
  3 均線多頭未發散 → 日線 MA5≥MA10≥MA20≥MA60 且 收盤未過度乖離 MA20（硬篩）
  4 量能放大   → 今日量 ≥ 前 20 日均量 × 1.5（硬篩）
  + 型態加分   → 均線糾結(盤整) / 波動收縮(ATR) / 收破近 20 日高(區間突破) / 週·月多頭
  + 三週期顯示 → 日線 resample 週/月，各報均線狀態（輔助人工判圖形）

型態(三角/杯柄)圖形不自動辨識（主觀、易誤判），只給可量化的近似指標 + 三週期狀態。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.shioaji_fetcher import (
    _get_api,
    _sync_fetch_daily,
    _tse_common_contracts,
    _SNAPSHOT_BATCH,
)

# ── 門檻常數（要調整篩選嚴格度改這裡）────────────────────────────────────────
MIN_CHANGE_PCT = 5.0       # 條件 2：當日漲幅門檻 %
VOL_BASELINE_DAYS = 20     # 條件 4：量能基準＝前 N 日均量
VOL_MULT = 1.5             # 條件 4：今日量需 ≥ 基準 × 此倍數
MA_CONVERGED_MAX = 0.05    # 型態：MA5/10/20 帶寬 / MA20 ≤ 5% → 均線糾結(盤整中)
EXTEND_MAX = 0.12          # 條件 3：收盤高於 MA20 超過 12% → 過度乖離(發散)，排除
BREAKOUT_LOOKBACK = 20     # 型態：收盤 > 前 N 日最高 → 區間突破
ATR_FAST, ATR_SLOW = 5, 20 # 型態：ATR5 < ATR20 → 波動收縮
DEEP_LIMIT = 40            # 深度分析上限（漲幅榜過長時，只深掃漲最多的前 N 檔）
DAILY_LOOKBACK = 260       # 抓日線根數（夠日 MA60 / 週 MA20 / 月 MA6）
BREADTH_BULL = 0.50        # 上漲家數占比 ≥ → 大盤偏多
BREADTH_BEAR = 0.40        # 上漲家數占比 < → 大盤偏空
BOWL_DEEP_LIMIT = 50       # 碗型+爆量篩選：依今日成交量排序，只深掃前 N 檔


@dataclass(frozen=True)
class TimeframeState:
    label: str    # 月 / 週 / 日
    trend: str    # 多頭 / 盤整 / 空頭 / 資料不足


@dataclass(frozen=True)
class ScanCandidate:
    code: str
    name: str
    change_rate: float
    close: float
    volume: int          # 今日累計量（張）
    vol_ratio: float     # 今日量 / 前 20 日均量
    score: int           # 型態加分（0–5）
    tags: tuple[str, ...]
    tf_monthly: TimeframeState
    tf_weekly: TimeframeState
    tf_daily: TimeframeState


@dataclass(frozen=True)
class ScanResult:
    candidates: tuple[ScanCandidate, ...]  # 通過四關、依 score→漲幅排序
    scanned: int            # snapshot 報價成功數
    raw_gainers: int        # 漲幅 ≥ 門檻數（硬篩前）
    advancers: int
    decliners: int
    market_state: str       # 偏多 / 中性 / 偏空
    market_ok: bool         # 是否適合進場（偏空→False）
    deep_analyzed: int      # 實際深度分析檔數


@dataclass(frozen=True)
class BowlScanResult:
    candidates: tuple[ScanCandidate, ...]  # 通過「碗型盤整+爆量+突破」三關，依 score→量比排序
    scanned: int            # snapshot 報價成功數
    deep_analyzed: int      # 實際深度分析檔數（依今日量排序取前 BOWL_DEEP_LIMIT）
    market_state: str       # 偏多 / 中性 / 偏空
    market_ok: bool


def _ma(close: pd.Series, n: int) -> float:
    if len(close) < n:
        return float("nan")
    return float(close.iloc[-n:].mean())


def _atr(df: pd.DataFrame, n: int) -> float:
    if len(df) < n + 1:
        return float("nan")
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())


def _tf_state(close: pd.Series, fast: int, slow: int, label: str) -> TimeframeState:
    """單一週期均線狀態：多頭 / 空頭 / 盤整。"""
    if len(close) < slow:
        return TimeframeState(label, "資料不足")
    maf = float(close.iloc[-fast:].mean())
    mas = float(close.iloc[-slow:].mean())
    last = float(close.iloc[-1])
    if last >= maf >= mas:
        trend = "多頭"
    elif last <= maf <= mas:
        trend = "空頭"
    else:
        trend = "盤整"
    return TimeframeState(label, trend)


def _analyze(code: str, name: str, change_rate: float, close: float, today_vol: int):
    """對單一候選跑日線深度分析。回傳 ScanCandidate 或 None（硬篩未過 / 資料不足）。"""
    df = _sync_fetch_daily(code, DAILY_LOOKBACK)
    if df.empty or len(df) < VOL_BASELINE_DAYS + 1 or len(df) < 60:
        return None

    c = df["close"]
    ma5, ma10, ma20, ma60 = _ma(c, 5), _ma(c, 10), _ma(c, 20), _ma(c, 60)
    if any(np.isnan(x) for x in (ma5, ma10, ma20, ma60)) or ma20 <= 0:
        return None

    # 條件 3：均線多頭排列 + 未過度乖離（發散）
    ma_bull = ma5 >= ma10 >= ma20 >= ma60
    extend = (close - ma20) / ma20
    not_extended = extend <= EXTEND_MAX

    # 條件 4：今日量 ≥ 前 20 日均量 × 1.5
    avg20 = float(df["volume"].iloc[-(VOL_BASELINE_DAYS + 1):-1].mean())
    vol_ratio = (today_vol / avg20) if avg20 > 0 else 0.0
    vol_ok = vol_ratio >= VOL_MULT

    # 硬篩：四關（漲幅已在 caller 過濾）→ 均線多頭 + 未發散 + 量能
    if not (ma_bull and not_extended and vol_ok):
        return None

    # 型態加分（可量化近似）
    spread = (max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / ma20
    converged = spread <= MA_CONVERGED_MAX
    atr_f, atr_s = _atr(df, ATR_FAST), _atr(df, ATR_SLOW)
    contraction = (not np.isnan(atr_f)) and (not np.isnan(atr_s)) and atr_f < atr_s
    prior_high = float(df["high"].iloc[-(BREAKOUT_LOOKBACK + 1):-1].max())
    breakout = close > prior_high

    tf_d = _tf_state(c, 5, 20, "日")
    wk = df["close"].resample("W").last().dropna()
    mo = df["close"].resample("ME").last().dropna()
    tf_w = _tf_state(wk, 5, 20, "週")
    tf_m = _tf_state(mo, 3, 6, "月")

    tags: list[str] = []
    score = 0
    if converged:
        score += 1; tags.append("均線糾結")
    if contraction:
        score += 1; tags.append("波動收縮")
    if breakout:
        score += 1; tags.append("破20日高")
    if tf_w.trend == "多頭":
        score += 1; tags.append("週多頭")
    if tf_m.trend == "多頭":
        score += 1; tags.append("月多頭")

    return ScanCandidate(
        code=code, name=name, change_rate=change_rate, close=close,
        volume=today_vol, vol_ratio=vol_ratio, score=score, tags=tuple(tags),
        tf_monthly=tf_m, tf_weekly=tf_w, tf_daily=tf_d,
    )


def _sync_scan() -> ScanResult:
    api = _get_api()
    contracts = _tse_common_contracts(api)
    by_code = {c.code: c for c in contracts}

    advancers = decliners = scanned = 0
    raw: list[tuple[str, float, float, int]] = []  # (code, change_rate, close, vol)
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
            rate = float(getattr(s, "change_rate", 0.0) or 0.0)
            if rate > 0:
                advancers += 1
            elif rate < 0:
                decliners += 1
            if rate >= MIN_CHANGE_PCT:
                raw.append((str(getattr(s, "code", "")), rate,
                            float(getattr(s, "close", 0.0) or 0.0), vol))

    # 大盤 breadth → market_state
    breadth = (advancers / scanned) if scanned else 0.0
    if breadth >= BREADTH_BULL:
        market_state, market_ok = "偏多", True
    elif breadth >= BREADTH_BEAR:
        market_state, market_ok = "中性", True
    else:
        market_state, market_ok = "偏空", False

    # 深度分析：漲幅高→低，只掃前 DEEP_LIMIT 檔
    raw.sort(key=lambda x: x[1], reverse=True)
    deep = raw[:DEEP_LIMIT]
    survivors: list[ScanCandidate] = []
    for code, rate, close, vol in deep:
        try:
            cand = _analyze(code, (getattr(by_code.get(code), "name", "") or code),
                            rate, close, vol)
        except Exception:
            cand = None
        if cand is not None:
            survivors.append(cand)

    survivors.sort(key=lambda c: (c.score, c.change_rate), reverse=True)
    return ScanResult(
        candidates=tuple(survivors), scanned=scanned, raw_gainers=len(raw),
        advancers=advancers, decliners=decliners,
        market_state=market_state, market_ok=market_ok, deep_analyzed=len(deep),
    )


async def scan() -> ScanResult:
    """跑當沖選股篩選（snapshot + 逐檔日線深度分析）。在 thread 執行不阻塞 event loop。"""
    return await asyncio.to_thread(_sync_scan)


def _analyze_bowl(code: str, name: str, change_rate: float, close: float, today_vol: int):
    """碗型整理底部+爆量突破：底部均線糾結 → 今日爆量 → 收破前 20 日高。回傳 ScanCandidate 或 None。"""
    df = _sync_fetch_daily(code, DAILY_LOOKBACK)
    if df.empty or len(df) < VOL_BASELINE_DAYS + BREAKOUT_LOOKBACK + 5:
        return None

    # 條件：今日量 ≥ 前 20 日均量 × 1.5
    avg20 = float(df["volume"].iloc[-(VOL_BASELINE_DAYS + 1):-1].mean())
    vol_ratio = (today_vol / avg20) if avg20 > 0 else 0.0
    vol_ok = vol_ratio >= VOL_MULT

    # 條件：收盤突破前 20 日高（不含今日）
    prior_high = float(df["high"].iloc[-(BREAKOUT_LOOKBACK + 1):-1].max())
    breakout = close > prior_high

    if not (vol_ok and breakout):
        return None

    # 條件：突破前（不含今日）均線糾結 → 碗型底部盤整
    c = df["close"]
    c_prior = c.iloc[:-1]
    ma5p, ma10p, ma20p = _ma(c_prior, 5), _ma(c_prior, 10), _ma(c_prior, 20)
    if any(np.isnan(x) for x in (ma5p, ma10p, ma20p)) or ma20p <= 0:
        return None
    spread = (max(ma5p, ma10p, ma20p) - min(ma5p, ma10p, ma20p)) / ma20p
    converged = spread <= MA_CONVERGED_MAX
    if not converged:
        return None

    atr_f, atr_s = _atr(df, ATR_FAST), _atr(df, ATR_SLOW)
    contraction = (not np.isnan(atr_f)) and (not np.isnan(atr_s)) and atr_f < atr_s

    tf_d = _tf_state(c, 5, 20, "日")
    wk = df["close"].resample("W").last().dropna()
    mo = df["close"].resample("ME").last().dropna()
    tf_w = _tf_state(wk, 5, 20, "週")
    tf_m = _tf_state(mo, 3, 6, "月")

    tags = ["碗型盤整", "爆量", "破20日高"]
    score = 3
    if contraction:
        score += 1; tags.append("波動收縮")
    if tf_w.trend == "多頭":
        score += 1; tags.append("週多頭")
    if tf_m.trend == "多頭":
        score += 1; tags.append("月多頭")

    return ScanCandidate(
        code=code, name=name, change_rate=change_rate, close=close,
        volume=today_vol, vol_ratio=vol_ratio, score=score, tags=tuple(tags),
        tf_monthly=tf_m, tf_weekly=tf_w, tf_daily=tf_d,
    )


def _sync_bowl_scan() -> BowlScanResult:
    api = _get_api()
    contracts = _tse_common_contracts(api)
    by_code = {c.code: c for c in contracts}

    advancers = decliners = scanned = 0
    raw: list[tuple[str, float, float, int]] = []  # (code, change_rate, close, vol)
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
            rate = float(getattr(s, "change_rate", 0.0) or 0.0)
            if rate > 0:
                advancers += 1
            elif rate < 0:
                decliners += 1
            raw.append((str(getattr(s, "code", "")), rate,
                        float(getattr(s, "close", 0.0) or 0.0), vol))

    breadth = (advancers / scanned) if scanned else 0.0
    if breadth >= BREADTH_BULL:
        market_state, market_ok = "偏多", True
    elif breadth >= BREADTH_BEAR:
        market_state, market_ok = "中性", True
    else:
        market_state, market_ok = "偏空", False

    # 依今日成交量（不看漲跌）排序，只深掃量最大的前 BOWL_DEEP_LIMIT 檔
    raw.sort(key=lambda x: x[3], reverse=True)
    deep = raw[:BOWL_DEEP_LIMIT]
    survivors: list[ScanCandidate] = []
    for code, rate, close, vol in deep:
        try:
            cand = _analyze_bowl(code, (getattr(by_code.get(code), "name", "") or code),
                                  rate, close, vol)
        except Exception:
            cand = None
        if cand is not None:
            survivors.append(cand)

    survivors.sort(key=lambda c: (c.score, c.vol_ratio), reverse=True)
    return BowlScanResult(
        candidates=tuple(survivors), scanned=scanned,
        deep_analyzed=len(deep), market_state=market_state, market_ok=market_ok,
    )


async def bowl_scan() -> BowlScanResult:
    """跑碗型底部+爆量突破篩選（snapshot + 逐檔日線深度分析）。在 thread 執行不阻塞 event loop。"""
    return await asyncio.to_thread(_sync_bowl_scan)
