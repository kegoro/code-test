"""潛力股掃描器 — 依「6 條技術特性」對中大型活躍股計分排名。

供 smc_bot `/potential` 指令用。

資料源（完全不碰 Shioaji，避免 30 天 kbar 上限 + 451 連線衝突）：
  - 活躍股清單：TWSE OpenAPI STOCK_DAY_ALL + TPEX OpenAPI（各一次、含成交值）→ 依成交值排序取前 N
  - 個股日線  ：FinMind 免費匿名（不帶 token、非還原日線；收盤級資料、不含當日半根 K）

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
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

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
TOP_N = 150              # 中大型活躍股：依今日成交值排序、只深掃前 N 檔（FinMind 免費匿名層上限保守值）
DEFAULT_MIN_SCORE = 4

# ── FinMind / 交易所 OpenAPI ──────────────────────────────────────────────
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_PRICE_DATASET = "TaiwanStockPrice"        # 非還原、免費
_PRICE_LOOKBACK_DAYS = 420                  # 暖機 MA60 + MACD26 + 60 日波段
_TWSE_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
_MAX_CONCURRENCY = 4     # FinMind 免費版限流，並發壓低
_REQUEST_GAP = 0.35      # 每次請求後小睡（秒）

COND_MARK = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}
_DEBUG_PATH = Path(__file__).resolve().parent / "_potential_debug.txt"


@dataclass(frozen=True)
class PotentialCandidate:
    code: str
    name: str
    trade_value: float       # 今日成交值（元），活躍度排序用
    close: float
    score: int
    conds: tuple[int, ...]
    rsi: float
    fib_retr: float          # 回調比例（NaN=無有效波段）
    vol_ratio: float         # 今日量 / 20日均量


@dataclass(frozen=True)
class PotentialResult:
    candidates: tuple[PotentialCandidate, ...]  # 依 (score, trade_value) 排序
    scanned: int            # 活躍股清單總檔數（TWSE+TPEX）
    deep_analyzed: int      # 實際抓到日線、完成計分的檔數
    min_score: int


def _is_common_stock(code: str) -> bool:
    """4 位數字、非 00 開頭（濾掉 ETF/權證/債券）。"""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def _to_num(x) -> float:
    return pd.to_numeric(str(x).replace(",", "").strip(), errors="coerce")


async def _fetch_twse_liquid() -> dict[str, tuple[str, float]]:
    """{code: (name, trade_value)} 上市。"""
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.get(_TWSE_DAY_ALL_URL, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
        rows = r.json()
    except Exception:
        return {}
    out: dict[str, tuple[str, float]] = {}
    for d in rows:
        code = str(d.get("Code", "")).strip()
        tv = _to_num(d.get("TradeValue"))
        if _is_common_stock(code) and pd.notna(tv):
            out[code] = (str(d.get("Name", "")).strip(), float(tv))
    return out


async def _fetch_tpex_liquid() -> dict[str, tuple[str, float]]:
    """{code: (name, trade_value)} 上櫃。"""
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.get(_TPEX_DAILY_URL, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
        rows = r.json()
    except Exception:
        return {}
    out: dict[str, tuple[str, float]] = {}
    for d in rows:
        code = str(d.get("SecuritiesCompanyCode", "")).strip()
        tv = _to_num(d.get("TransactionAmount"))
        if _is_common_stock(code) and pd.notna(tv):
            out[code] = (str(d.get("CompanyName", "")).strip(), float(tv))
    return out


async def _build_universe(top_n: int) -> tuple[list[tuple[str, str, float]], int]:
    """回傳 (依成交值排序的前 top_n 檔, 全市場活躍檔數)。"""
    twse, tpex = await asyncio.gather(_fetch_twse_liquid(), _fetch_tpex_liquid())
    merged = {**twse, **tpex}
    ranked = sorted(merged.items(), key=lambda kv: kv[1][1], reverse=True)
    top = [(code, nm, tv) for code, (nm, tv) in ranked[:top_n]]
    return top, len(merged)


_sema = asyncio.Semaphore(_MAX_CONCURRENCY)


async def _finmind_get(dataset: str, data_id: str, start_date: str) -> pd.DataFrame:
    """免費直連 FinMind（不帶 token）；失敗回空 DataFrame。"""
    params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
    async with _sema:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(_FINMIND_URL, params=params)
            payload = resp.json()
        except Exception:
            return pd.DataFrame()
        finally:
            await asyncio.sleep(_REQUEST_GAP)
    if payload.get("status") != 200:
        return pd.DataFrame()
    return pd.DataFrame(payload.get("data", []))


async def _fetch_ohlcv(code: str) -> pd.DataFrame:
    start = (datetime.today() - timedelta(days=_PRICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    df = await _finmind_get(_PRICE_DATASET, code, start)
    need = {"date", "open", "max", "min", "close", "Trading_Volume"}
    if df.empty or not need.issubset(df.columns):
        return pd.DataFrame()
    out = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    out = out[["date", "open", "high", "low", "close", "volume"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


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


async def scan(min_score: int = DEFAULT_MIN_SCORE) -> PotentialResult:
    """跑潛力股 6 條件掃描（TWSE/TPEX 取活躍股 + FinMind 日線計分）。"""
    universe, total = await _build_universe(TOP_N)

    async def _one(code: str, name: str, tv: float) -> PotentialCandidate | None:
        df = await _fetch_ohlcv(code)
        if df.empty:
            return None
        score, conds, rsi, fib, vr = _score_df(df)
        return PotentialCandidate(
            code=code, name=name, trade_value=tv, close=float(df["close"].iloc[-1]),
            score=score, conds=tuple(conds), rsi=rsi, fib_retr=fib, vol_ratio=vr,
        )

    results = await asyncio.gather(*[_one(c, n, tv) for c, n, tv in universe])
    scored = [r for r in results if r is not None]
    survivors = sorted(
        [r for r in scored if r.score >= min_score],
        key=lambda r: (r.score, r.trade_value), reverse=True,
    )

    # 輕量診斷（確認掃描健康度）
    try:
        hist = {i: 0 for i in range(7)}
        for r in scored:
            hist[r.score] = hist.get(r.score, 0) + 1
        _DEBUG_PATH.write_text(
            f"min_score={min_score} universe={total} top_n={len(universe)} "
            f"got_data={len(scored)} no_data={len(universe) - len(scored)}\n"
            f"score_hist(0..6)={[hist[i] for i in range(7)]}\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    return PotentialResult(
        candidates=tuple(survivors), scanned=total,
        deep_analyzed=len(scored), min_score=min_score,
    )
