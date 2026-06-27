"""
潛力股掃描器 — 依「6 條技術特性」對中大型活躍股計分排名。

6 條(出自使用者選股總結圖 IMG_7051), 量化判定:
  ① 量放大        : 今日量 ≥ VOL_MULT × 20日均量
  ② 均線多頭      : MA20 上彎(今 > 5日前) 且 收盤 > MA20
  ③ 布林開口      : 帶寬(上-下)/中軌 比 5 日前放大 且 收盤 > 中軌
  ④ 斐波回調      : 近 LOOKBACK 日「低→高」波段, 回調落在 38.2%~61.8%(含容差)
  ⑤ RSI 止穩翻揚  : RSI(14) 在 45~60 且 今天 > 昨天
  ⑥ MACD 金叉     : 近 3 日內 DIF 上穿 DEA(柱由負翻正)

⚠️ 6 條不可能同時成立(③突破 vs ④拉回 互斥), 故用「計分」: 中越多越接近發動。
   預設撈 score ≥ MIN_SCORE 的, 依 (分數, 成交值) 排序。

資料源:
  - 活躍股清單: TWSE OpenAPI STOCK_DAY_ALL + TPEX OpenAPI(各一次, 含成交值)→ 成交值排序取前 N
  - 個股日線 : FinMind 免費非還原(複用 concept_index 的 _finmind_get)

CLI:
  .venv/Scripts/python.exe -m sector.breakout_scan                 # 前300活躍股, score≥4
  .venv/Scripts/python.exe -m sector.breakout_scan --top 200 --min-score 3
  .venv/Scripts/python.exe -m sector.breakout_scan --csv out.csv
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import httpx
import pandas as pd

from sector.concept_index import _finmind_get, _PRICE_DATASET, _PRICE_LOOKBACK_DAYS
from datetime import datetime, timedelta

_TWSE_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# ── 判定參數 (可調) ───────────────────────────────────────────────
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
DEFAULT_TOP = 200          # FinMind 免費匿名層 ~200 次/批就被擋, 超過會連續抓不到
DEFAULT_MIN_SCORE = 4

_COND_MARK = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}


@dataclass(frozen=True)
class ScanRow:
    code: str
    name: str
    trade_value: float       # 成交值(元), 流動性排序用
    close: float
    score: int
    conds: tuple[int, ...]   # 命中的條件編號
    rsi: float
    fib_retr: float          # 回調比例(NaN=無有效波段)


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


def _is_common_stock(code: str) -> bool:
    """4 位數字、非 00 開頭(濾掉 ETF/權證/債券)。"""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


async def build_liquid_universe(top_n: int) -> list[tuple[str, str, float]]:
    twse, tpex = await asyncio.gather(_fetch_twse_liquid(), _fetch_tpex_liquid())
    merged = {**twse, **tpex}
    ranked = sorted(merged.items(), key=lambda kv: kv[1][1], reverse=True)
    return [(code, nm, tv) for code, (nm, tv) in ranked[:top_n]]


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
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def score_stock(df: pd.DataFrame) -> tuple[int, list[int], float, float]:
    """回傳 (score, 命中條件list, 最新RSI, 斐波回調比例)。資料不足回 (0,[],nan,nan)。"""
    if len(df) < MIN_BARS:
        return 0, [], float("nan"), float("nan")
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    conds: list[int] = []

    # ① 量放大
    vol_ma = vol.rolling(MA_PERIOD).mean()
    if vol.iloc[-1] >= VOL_MULT * vol_ma.iloc[-1]:
        conds.append(1)

    # ② 均線多頭
    ma = close.rolling(MA_PERIOD).mean()
    if ma.iloc[-1] > ma.iloc[-1 - SLOPE_LOOKBACK] and close.iloc[-1] > ma.iloc[-1]:
        conds.append(2)

    # ③ 布林開口
    std = close.rolling(MA_PERIOD).std()
    mid = ma
    bandwidth = (4 * std) / mid          # (上-下)/中 = 4σ/MA
    if bandwidth.iloc[-1] > bandwidth.iloc[-1 - BAND_LOOKBACK] * BAND_OPEN_RATIO and close.iloc[-1] > mid.iloc[-1]:
        conds.append(3)

    # ④ 斐波回調: 近 FIB_LOOKBACK 找最低, 其後最高, 回調比例
    window = df.iloc[-FIB_LOOKBACK:]
    low_idx = window["low"].idxmin()
    after = window.loc[low_idx:]
    fib_retr = float("nan")
    if len(after) >= 2:
        swing_low = window["low"].min()
        swing_high = after["high"].max()
        if swing_high > swing_low:
            fib_retr = (swing_high - close.iloc[-1]) / (swing_high - swing_low)
            if FIB_LOW - FIB_TOL <= fib_retr <= FIB_HIGH + FIB_TOL:
                conds.append(4)

    # ⑤ RSI 止穩翻揚
    rsi = _rsi(close)
    if RSI_LOW <= rsi.iloc[-1] <= RSI_HIGH and rsi.iloc[-1] > rsi.iloc[-2]:
        conds.append(5)

    # ⑥ MACD 金叉(近 CROSS_WINDOW 日柱由負翻正)
    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = dif - dea
    if hist.iloc[-1] > 0 and hist.iloc[-1 - CROSS_WINDOW] < 0:
        conds.append(6)

    return len(conds), conds, float(rsi.iloc[-1]), fib_retr


async def scan(top_n: int, min_score: int) -> tuple[list[ScanRow], int, int]:
    """回傳 (符合 min_score 的列, 實際掃描檔數, 抓不到資料檔數)。"""
    universe = await build_liquid_universe(top_n)
    sem = asyncio.Semaphore(4)

    async def _one(code: str, name: str, tv: float) -> ScanRow | None:
        async with sem:
            df = await _fetch_ohlcv(code)
        if df.empty:
            return None
        score, conds, rsi, fib = score_stock(df)
        return ScanRow(code, name, tv, float(df["close"].iloc[-1]), score, tuple(conds), rsi, fib)

    results = await asyncio.gather(*[_one(c, n, tv) for c, n, tv in universe])
    scanned = [r for r in results if r is not None]
    no_data = len(results) - len(scanned)
    hits = sorted(
        [r for r in scanned if r.score >= min_score],
        key=lambda r: (r.score, r.trade_value),
        reverse=True,
    )
    return hits, len(scanned), no_data


def _print_table(hits: list[ScanRow], scanned: int, no_data: int, top_n: int, min_score: int) -> None:
    print(f"\n=== 潛力股掃描  (活躍股前 {top_n} 檔, 實掃 {scanned}, 抓不到 {no_data}) ===")
    print(f"條件: ①量放大 ②均線多頭 ③布林開口 ④斐波回調 ⑤RSI翻揚 ⑥MACD金叉  | 門檻 score≥{min_score}\n")
    if not hits:
        print("(無符合, 可降低 --min-score 再試)")
        return
    print(f"{'代號':<6}{'名稱':<9}{'分':>3}  {'命中':<14}{'收盤':>9}{'RSI':>6}{'回調%':>7}")
    for r in hits:
        marks = "".join(_COND_MARK[c] for c in r.conds)
        fib = f"{r.fib_retr*100:5.1f}" if pd.notna(r.fib_retr) else "  -- "
        print(f"{r.code:<6}{r.name:<9}{r.score:>3}  {marks:<14}{r.close:>9.2f}{r.rsi:>6.1f}{fib:>7}")


async def _amain() -> None:
    parser = argparse.ArgumentParser(description="潛力股 6 條件掃描器")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="活躍股取前 N 檔(成交值)")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE, help="最低命中條件數")
    parser.add_argument("--csv", default=None, help="另存 CSV 路徑")
    args = parser.parse_args()

    hits, scanned, no_data = await scan(args.top, args.min_score)
    _print_table(hits, scanned, no_data, args.top, args.min_score)

    if args.csv and hits:
        pd.DataFrame([{
            "code": r.code, "name": r.name, "score": r.score,
            "conds": "".join(_COND_MARK[c] for c in r.conds),
            "close": r.close, "rsi": round(r.rsi, 1),
            "fib_retr": round(r.fib_retr, 3) if pd.notna(r.fib_retr) else None,
            "trade_value": r.trade_value,
        } for r in hits]).to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\n💾 已存 CSV: {args.csv}")


if __name__ == "__main__":
    asyncio.run(_amain())
