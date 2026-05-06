"""
連續五日量縮不破低 選股策略

V1 — 連續 N 日每日成交量比前一日下滑至少 threshold（預設 10%）
V2 — 連續 N 日每日最低價 >= 前一日最低價（低點不破，賣壓未擴大）

資料來源：yfinance（台股格式 2330.TW）
掃描方式：ThreadPoolExecutor（max_workers=5）+ time.sleep(0.5) 防 rate limit
"""
import time
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tqdm import tqdm
from loguru import logger


@dataclass
class VolShrinkMatch:
    symbol: str
    name: str
    dates: list[str]              # 符合條件的連續 N 天日期
    closes: list[float]           # 收盤價序列
    volumes: list[int]            # 成交量序列（yfinance 單位：股）
    vol_shrink_pcts: list[float]  # 量縮幅度（%），與前一日相比
    lows: list[float]             # 最低價序列


def fetch_stock_data(ticker: str, period: str = "30d", market: str = "twse") -> pd.DataFrame:
    """
    用 yfinance 抓取 OHLCV 資料。
    - market="twse" → 補 .TW（上市）；market="otc" → 補 .TWO（上櫃）
    - 已帶後綴的不修改
    - 回傳欄位：date, open, high, low, close, volume（全小寫）
    - volume 單位：股（÷1000 = 張）
    """
    if "." not in ticker:
        suffix = ".TWO" if market == "otc" else ".TW"
        ticker = f"{ticker}{suffix}"

    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if df.empty:
        return df

    df = df.reset_index()
    # 相容 yfinance 新版多層欄位（下載多支股票時欄位為 tuple）
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    df["date"] = pd.to_datetime(df["date"])
    return df


def check_volume_shrink(
    df: pd.DataFrame,
    consecutive: int = 5,
    threshold: float = 0.10,
) -> bool:
    """
    檢查最後 consecutive 日，每日成交量比前一日下滑至少 threshold（10%）。
    需要 consecutive+1 筆才能產生 consecutive 個比較對。
    """
    if len(df) < consecutive + 1:
        return False
    vols = df["volume"].iloc[-(consecutive + 1):].values
    for i in range(1, len(vols)):
        prev, curr = vols[i - 1], vols[i]
        if prev <= 0:
            return False
        if (prev - curr) / prev < threshold:
            return False
    return True


def check_low_not_break(df: pd.DataFrame, consecutive: int = 5) -> bool:
    """
    檢查最後 consecutive 日，每日最低價 >= 前一日最低價（低點不破）。
    """
    if len(df) < consecutive + 1:
        return False
    lows = df["low"].iloc[-(consecutive + 1):].values
    for i in range(1, len(lows)):
        if lows[i] < lows[i - 1]:
            return False
    return True


def _scan_one(
    symbol: str,
    name: str,
    consecutive: int,
    threshold: float,
    min_avg_volume_lots: int = 2000,
    market: str = "twse",
) -> VolShrinkMatch | None:
    """掃描單支股票。符合條件回傳 VolShrinkMatch，否則回傳 None。"""
    time.sleep(0.5)  # 避免 yfinance rate limit
    try:
        df = fetch_stock_data(symbol, period="30d", market=market)
        if df.empty or len(df) < consecutive + 1:
            return None

        # 均量過濾：yfinance 回傳單位為「股」，1張 = 1000股
        avg_vol_lots = df["volume"].iloc[-5:].mean() / 1000
        if avg_vol_lots < min_avg_volume_lots:
            logger.debug(f"[vol_shrink] {symbol} 均量 {avg_vol_lots:.0f}張 < {min_avg_volume_lots}張 — 跳過")
            return None

        if not check_volume_shrink(df, consecutive, threshold):
            return None
        if not check_low_not_break(df, consecutive):
            return None

        # 取最後 consecutive+1 列（需要第 0 列當比較基準）
        tail = df.iloc[-(consecutive + 1):]
        all_vols = tail["volume"].astype(int).tolist()

        # 顯示用資料：最後 consecutive 天（基準日不顯示）
        dates = tail["date"].iloc[1:].dt.strftime("%Y-%m-%d").tolist()
        closes = [round(float(v), 2) for v in tail["close"].iloc[1:]]
        volumes = all_vols[1:]
        lows = [round(float(v), 2) for v in tail["low"].iloc[1:]]

        # 量縮幅度 = (前一日 - 當日) / 前一日 × 100
        vol_shrink_pcts = [
            round((all_vols[i - 1] - all_vols[i]) / all_vols[i - 1] * 100, 1)
            if all_vols[i - 1] > 0 else 0.0
            for i in range(1, len(all_vols))
        ]

        return VolShrinkMatch(
            symbol=symbol,
            name=name,
            dates=dates,
            closes=closes,
            volumes=volumes,
            vol_shrink_pcts=vol_shrink_pcts,
            lows=lows,
        )

    except Exception as exc:
        logger.debug(f"[vol_shrink] {symbol} 跳過: {type(exc).__name__}: {exc}")
        return None


def scan_stocks(
    ticker_list: list[dict],
    consecutive: int = 5,
    threshold: float = 0.10,
    max_workers: int = 5,
    min_avg_volume_lots: int = 2000,
) -> list[VolShrinkMatch]:
    """
    批量掃描股票清單，找出符合「連續五日量縮不破低」型態的標的。

    ticker_list: [{"symbol": "2330", "name": "台積電", "market": "twse"/"otc"}, ...]
    min_avg_volume_lots: 近5日均量門檻（張），低於此值跳過（預設 2000張）
    回傳按股票代號排序的 VolShrinkMatch 清單。
    """
    matches: list[VolShrinkMatch] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _scan_one,
                s["symbol"],
                s.get("name", s["symbol"]),
                consecutive,
                threshold,
                min_avg_volume_lots,
                s.get("market", "twse"),   # 上市用 .TW，上櫃用 .TWO
            ): s["symbol"]
            for s in ticker_list
        }
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="量縮不破低掃描",
            unit="支",
        ):
            result = future.result()
            if result is not None:
                matches.append(result)

    matches.sort(key=lambda m: m.symbol)
    return matches


def save_result_csv(matches: list[VolShrinkMatch], trading_date: str) -> Path:
    """
    儲存符合條件標的為 data/result_{YYYYMMDD}.csv。
    每支股票輸出 consecutive 列（每日一列）。
    """
    from config.settings import settings

    rows = []
    for m in matches:
        for d, c, v, pct, low in zip(
            m.dates, m.closes, m.volumes, m.vol_shrink_pcts, m.lows
        ):
            rows.append({
                "symbol":         m.symbol,
                "name":           m.name,
                "date":           d,
                "close":          c,
                "volume":         v,
                "vol_shrink_pct": pct,
                "low":            low,
            })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["symbol", "name", "date", "close", "volume", "vol_shrink_pct", "low"]
    )
    date_str = trading_date.replace("-", "")
    path = Path(settings.data_dir) / f"result_{date_str}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info(f"[vol_shrink] CSV saved → {path}")
    return path


def format_result(matches: list[VolShrinkMatch]) -> str:
    """格式化輸出字串，適用於 console 列印。"""
    if not matches:
        return "本日無符合「連續五日量縮不破低」條件之標的。"

    sep = "=" * 60
    lines = [sep, f"  連續五日量縮不破低  共 {len(matches)} 檔", sep]
    for m in matches:
        lines.append(f"\n📌 {m.symbol}  {m.name}")
        lines.append(f"{'日期':<12} {'收盤':>7} {'成交量':>12} {'量縮%':>8} {'最低':>8}")
        lines.append("-" * 54)
        for d, c, v, pct, low in zip(
            m.dates, m.closes, m.volumes, m.vol_shrink_pcts, m.lows
        ):
            lines.append(
                f"{d:<12} {c:>7.2f} {v:>12,} {pct:>6.1f}%  {low:>8.2f}"
            )
    lines.append(f"\n{sep}")
    return "\n".join(lines)
