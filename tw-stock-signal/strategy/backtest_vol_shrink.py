"""
連續五日量縮不破低 回測模組

掃描過去 2 年歷史資料，找出所有型態發生日期，
套用 A + B1 + B2 條件過濾，計算型態後 5/10/20 日報酬率。

資料來源：yfinance（2y period）
"""
import time
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from tqdm import tqdm
from loguru import logger

from strategy.volume_shrink import check_volume_shrink, check_low_not_break

# ── 常數 ───────────────────────────────────────────────────────────────────────
BACKTEST_PERIOD    = "2y"
CONSECUTIVE        = 5
THRESHOLD          = 0.10
MIN_AVG_VOL_LOTS   = 2000
TRADING_DAYS_6M    = 126   # ~6個月
TRADING_DAYS_1Y    = 252   # ~1年
LOOKBACK_120D      = 120   # A條件：前120日內創年高


@dataclass
class BacktestResult:
    symbol:               str
    name:                 str
    market:               str
    pattern_date:         str     # 型態第5天日期
    close_on_pattern:     float
    vol_ratio:            float   # 型態日量 / 20MA量
    dist_from_52w_high:   float   # 距1年高點%（負值=低於高點）
    filter_a:             bool
    filter_a_reason:      str
    filter_b1:            bool
    filter_b1_reason:     str
    filter_b2:            bool
    filter_b2_reason:     str
    all_pass:             bool
    r5:                   Optional[float]
    r10:                  Optional[float]
    r20:                  Optional[float]


# ── 資料下載 ──────────────────────────────────────────────────────────────────

def _download(symbol: str, market: str) -> pd.DataFrame:
    """下載 2 年 OHLCV，統一欄位名稱為小寫。"""
    time.sleep(0.3)
    ticker = f"{symbol}.TWO" if market == "otc" else f"{symbol}.TW"
    df = yf.download(ticker, period=BACKTEST_PERIOD, auto_adjust=True, progress=False)
    if df.empty:
        return df
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── 型態掃描 ──────────────────────────────────────────────────────────────────

def find_all_pattern_indices(df: pd.DataFrame) -> list[int]:
    """
    在完整歷史 DataFrame 中找出所有型態命中位置（型態第5天的 row index）。
    非重疊去重：相隔 < CONSECUTIVE 天的第二個命中會被略過，
    確保同一波吸籌只計一次。
    """
    min_rows = CONSECUTIVE + 1
    hits: list[int] = []
    last_hit = -CONSECUTIVE - 1

    for i in range(min_rows, len(df) + 1):
        window = df.iloc[i - min_rows: i]
        end_idx = i - 1
        if end_idx - last_hit < CONSECUTIVE:
            continue
        if check_volume_shrink(window, CONSECUTIVE, THRESHOLD) and \
           check_low_not_break(window, CONSECUTIVE):
            hits.append(end_idx)
            last_hit = end_idx
    return hits


# ── 篩選條件 A ────────────────────────────────────────────────────────────────

def check_filter_a(df: pd.DataFrame, idx: int) -> tuple[bool, str]:
    """
    A：長多結構（符合其一即可）
    A1: 前120日內曾創近1年（252日）新高
    A2: 60MA向上，且股價站在60MA之上
    """
    if idx < 60:
        return False, "資料不足60日"

    close = float(df["close"].iat[idx])

    # A2: 60MA
    prices = df["close"].values
    ma60 = float(np.mean(prices[max(0, idx - 59): idx + 1]))
    if idx >= 61:
        ma60_prev = float(np.mean(prices[max(0, idx - 60): idx]))
        if ma60 > ma60_prev and close > ma60:
            return True, f"60MA向上({ma60:.1f})且股價({close:.1f})站上60MA"

    # A1: 前120日內創1年新高
    if idx >= TRADING_DAYS_1Y:
        year_high = float(np.max(df["high"].values[idx - TRADING_DAYS_1Y: idx + 1]))
        if idx >= LOOKBACK_120D:
            recent_high = float(np.max(df["high"].values[idx - LOOKBACK_120D: idx + 1]))
            if recent_high >= year_high * 0.98:
                return True, f"前120日曾觸1年高（年高={year_high:.1f}）"
        return False, f"60MA未達標且前120日未創年高（年高={year_high:.1f}，現={close:.1f}）"

    return False, f"資料不足1年（{idx}日）且60MA未達標"


# ── 篩選條件 B1 ───────────────────────────────────────────────────────────────

def check_filter_b1(
    df: pd.DataFrame,
    idx: int,
    prev_hits: list[int],
) -> tuple[bool, str]:
    """
    B1：長期吸籌特徵（符合任一即可）
    b1a: 過去6個月大量下跌日 / 大量上漲日 < 0.5
    b1b: 過去6個月出現 ≥3 次量縮不破低型態（反覆蓄積）
    b1c: 過去6個月有 ≥2 次大量橫盤（churning，主力承接）
    """
    start_6m = max(0, idx - TRADING_DAYS_6M)
    hist = df.iloc[start_6m: idx + 1]

    if len(hist) < 20:
        return False, "近6個月資料不足20日"

    # 20日均量（用整段歷史最末20日）
    avg_vol = float(df["volume"].iloc[max(0, idx - 19): idx + 1].mean())
    if avg_vol <= 0:
        return False, "均量計算失敗"

    big_thresh = avg_vol * 2.0
    big_days = hist[hist["volume"] > big_thresh]

    # B1a
    if len(big_days) >= 2:
        big_up   = int((big_days["close"] >= big_days["open"]).sum())
        big_down = int((big_days["close"] <  big_days["open"]).sum())
        if big_up > 0:
            ratio = big_down / big_up
            if ratio < 0.5:
                return True, f"大量上漲/下跌比={ratio:.2f}<0.5（大量多為上漲日）"

    # B1b
    prior = [h for h in prev_hits if start_6m <= h < idx]
    if len(prior) >= 3:
        return True, f"近6個月累計{len(prior)+1}次量縮不破低（反覆蓄積）"

    # B1c: churning（大量但漲跌幅<0.5%）
    if len(big_days) >= 2:
        body_pct = abs(big_days["close"] - big_days["open"]) / big_days["open"].replace(0, np.nan)
        churn_count = int((body_pct < 0.005).sum())
        if churn_count >= 2:
            return True, f"近6個月出現{churn_count}次大量橫盤（主力暗中承接）"

    return False, "無明顯長期吸籌特徵（A+B1b均未達標）"


# ── 篩選條件 B2 ───────────────────────────────────────────────────────────────

def check_filter_b2(df: pd.DataFrame, idx: int) -> tuple[bool, str]:
    """
    B2：賣壓消失確認（B1成立才看這個）
    條件1: 近5日最大單日跌幅 < 1.5%
    條件2: 近5日無「量增價跌」日（量 > 20MA 且收跌）
    """
    if idx < 5:
        return False, "資料不足5日"

    window = df.iloc[idx - 4: idx + 1]
    pct_changes = window["close"].pct_change() * 100
    max_drop = float(pct_changes.min())  # NaN ignored by default

    if max_drop < -1.5:
        return False, f"近5日最大單日跌幅{max_drop:.1f}%（超過1.5%，賣壓仍在）"

    avg_vol_20 = float(df["volume"].iloc[max(0, idx - 19): idx + 1].mean())
    if avg_vol_20 > 0:
        for _, row in window.iterrows():
            if row["volume"] > avg_vol_20 and row["close"] < row["open"]:
                vr = row["volume"] / avg_vol_20
                return False, f"近5日出現量增價跌（量比{vr:.1f}x，收跌）"

    return True, f"近5日跌幅{max_drop:.1f}%，無量增價跌"


# ── 指標計算 ──────────────────────────────────────────────────────────────────

def _metrics(df: pd.DataFrame, idx: int) -> tuple[float, float]:
    """回傳 (量比, 距1年高點%)"""
    avg_vol = float(df["volume"].iloc[max(0, idx - 19): idx + 1].mean())
    vol_ratio = round(float(df["volume"].iat[idx]) / avg_vol, 2) if avg_vol > 0 else float("nan")

    lookback = min(idx + 1, TRADING_DAYS_1Y)
    year_high = float(df["high"].iloc[idx + 1 - lookback: idx + 1].max())
    close = float(df["close"].iat[idx])
    dist = round((close - year_high) / year_high * 100, 1) if year_high > 0 else float("nan")

    return vol_ratio, dist


def _fwd_return(df: pd.DataFrame, idx: int, days: int) -> Optional[float]:
    target = idx + days
    if target >= len(df):
        return None
    entry = float(df["close"].iat[idx])
    exit_ = float(df["close"].iat[target])
    return round((exit_ - entry) / entry * 100, 2)


# ── 單支股票回測 ──────────────────────────────────────────────────────────────

def backtest_one(stock: dict) -> list[BacktestResult]:
    """對單支股票執行完整回測，回傳所有 BacktestResult（含未通過過濾的）。"""
    symbol = stock["symbol"]
    name   = stock.get("name", symbol)
    market = stock.get("market", "twse")

    try:
        df = _download(symbol, market)
        if df.empty or len(df) < CONSECUTIVE + 20:
            return []

        # 均量過濾（以最新5日為準）
        if df["volume"].iloc[-5:].mean() / 1000 < MIN_AVG_VOL_LOTS:
            return []

        all_hits = find_all_pattern_indices(df)
        if not all_hits:
            return []

        results = []
        for hit_idx in all_hits:
            vol_ratio, dist_high = _metrics(df, hit_idx)

            fa,  fa_r  = check_filter_a(df, hit_idx)
            prev = [h for h in all_hits if h < hit_idx]
            fb1, fb1_r = check_filter_b1(df, hit_idx, prev)
            fb2, fb2_r = check_filter_b2(df, hit_idx) if fb1 else (False, "B1未通過")

            results.append(BacktestResult(
                symbol=symbol, name=name, market=market,
                pattern_date=df["date"].iat[hit_idx].strftime("%Y-%m-%d"),
                close_on_pattern=round(float(df["close"].iat[hit_idx]), 2),
                vol_ratio=vol_ratio,
                dist_from_52w_high=dist_high,
                filter_a=fa,    filter_a_reason=fa_r,
                filter_b1=fb1,  filter_b1_reason=fb1_r,
                filter_b2=fb2,  filter_b2_reason=fb2_r,
                all_pass=fa and fb1 and fb2,
                r5=_fwd_return(df, hit_idx, 5),
                r10=_fwd_return(df, hit_idx, 10),
                r20=_fwd_return(df, hit_idx, 20),
            ))

        return results

    except Exception as exc:
        logger.debug(f"[backtest] {symbol} 失敗: {type(exc).__name__}: {exc}")
        return []


# ── 全市場回測 ────────────────────────────────────────────────────────────────

def run_backtest(
    ticker_list: list[dict],
    max_workers: int = 8,
) -> list[BacktestResult]:
    """對 ticker_list 執行完整回測，回傳所有 BacktestResult（含未通過的，供統計用）。"""
    all_results: list[BacktestResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(backtest_one, s): s["symbol"] for s in ticker_list}
        for future in tqdm(as_completed(futures), total=len(futures), desc="回測中", unit="支"):
            try:
                all_results.extend(future.result())
            except Exception as exc:
                logger.debug(f"[backtest] future error: {exc}")

    all_results.sort(key=lambda r: (r.symbol, r.pattern_date))
    return all_results


# ── 儲存 CSV ──────────────────────────────────────────────────────────────────

def save_backtest_csv(results: list[BacktestResult], run_date: str) -> Path:
    """儲存完整回測結果（含未通過的）至 data/backtest_{YYYYMMDD}.csv。"""
    from config.settings import settings

    rows = [{
        "symbol":           r.symbol,
        "name":             r.name,
        "market":           r.market,
        "pattern_date":     r.pattern_date,
        "close":            r.close_on_pattern,
        "vol_ratio":        r.vol_ratio,
        "dist_52w_high%":   r.dist_from_52w_high,
        "filter_A":         r.filter_a,
        "A_reason":         r.filter_a_reason,
        "filter_B1":        r.filter_b1,
        "B1_reason":        r.filter_b1_reason,
        "filter_B2":        r.filter_b2,
        "B2_reason":        r.filter_b2_reason,
        "all_pass":         r.all_pass,
        "r5%":              r.r5,
        "r10%":             r.r10,
        "r20%":             r.r20,
    } for r in results]

    df_out = pd.DataFrame(rows) if rows else pd.DataFrame()
    date_str = run_date.replace("-", "")
    path = Path(settings.data_dir) / f"backtest_{date_str}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info(f"[backtest] CSV saved → {path}  ({len(rows)} rows)")
    return path


# ── 統計摘要 ──────────────────────────────────────────────────────────────────

def compute_summary(results: list[BacktestResult]) -> dict:
    """計算並回傳統計摘要字典。"""
    total_patterns = len(results)
    pass_a   = [r for r in results if r.filter_a]
    pass_ab1 = [r for r in results if r.filter_a and r.filter_b1]
    passed   = [r for r in results if r.all_pass]

    def _win_rate(lst, attr):
        vals = [getattr(r, attr) for r in lst if getattr(r, attr) is not None]
        if not vals:
            return None, None
        wins = sum(1 for v in vals if v > 0)
        return round(sum(vals) / len(vals), 2), round(wins / len(vals) * 100, 1)

    avg5,  wr5  = _win_rate(passed, "r5")
    avg10, wr10 = _win_rate(passed, "r10")
    avg20, wr20 = _win_rate(passed, "r20")

    # Top stocks by pass count
    from collections import Counter
    top_stocks = Counter(
        f"{r.symbol} {r.name}" for r in passed
    ).most_common(5)

    return {
        "total_patterns": total_patterns,
        "pass_a":         len(pass_a),
        "pass_ab1":       len(pass_ab1),
        "passed":         len(passed),
        "avg_r5": avg5,   "wr5":  wr5,
        "avg_r10": avg10, "wr10": wr10,
        "avg_r20": avg20, "wr20": wr20,
        "top_stocks": top_stocks,
    }
