"""
概念指數引擎 — 把一組相關概念股打包成一條正規化指數。

設計目標（使用者需求）:
  1. 兩種權重同時算出來:
       - 等權重 (equal-weight): 每檔先 rebase 到 100, 再取平均。看「整個族群氣氛」。
       - 市值加權 (market-cap): sum(price_i × shares_i) rebase 到 100。大型股主導。
  2. 指數疊 MA20 / MA60 (均線成本概念)。
  3. 正規化 MACD%  = (EMA12 − EMA26) ÷ EMA26 × 100
       這個百分比版本可跨品種比較; 三色:
         > +NEUTRAL_BAND  紅 (快線在慢線上 → 偏多/乖離大)
         介於 ±NEUTRAL_BAND 黃 (均線密集)
         < −NEUTRAL_BAND  綠 (偏空/乖離大向下)

資料源: FinMind 還原日線 (scrapers/finmind/price.py)。
市值股數: TaiwanStockBalanceSheet 的 CapitalStock(千元) ÷ 10 × 1000。

CLI:
  .venv/Scripts/python.exe -m sector.concept_index            # 算 active 第一個族群
  .venv/Scripts/python.exe -m sector.concept_index --family 光通訊與矽光子CPO
  .venv/Scripts/python.exe -m sector.concept_index --no-chart # 只印數字不畫圖
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

_PKG_ROOT = Path(__file__).resolve().parent.parent

# 概念股清單與專案共用 data/ 目錄 (在 repo 根, tw-stock-signal 的上一層)
_CONCEPT_PATH = _PKG_ROOT.parent / "data" / "concept_groups.json"

# ── FinMind 免費直連 ──────────────────────────────────────────────
# 註: 專案 .env 的 FINMIND_API_TOKEN 已失效("Token is illegal"), 且還原日線
# TaiwanStockPriceAdj 已改付費等級。本引擎刻意「不帶 token、用免費非還原日線」,
# 自給自足、不被壞 token 連累。對 rebase 後的氣氛指數影響極小 (僅除權息小缺口)。
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
# TWSE 官方 OpenAPI: 全市場「當日」收盤快照 (僅上市, 不含上櫃; 無 token、永不過期)。
# 用途: 收盤後把上市股最新一根用官方價補上 (FinMind 免費版有時會 lag 一天)。
_TWSE_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_PRICE_DATASET = "TaiwanStockPrice"          # 非還原, 免費
_BALANCE_DATASET = "TaiwanStockBalanceSheet"  # 免費; 取 CapitalStock 換算股數
_BALANCE_LOOKBACK = "2024-01-01"
_PRICE_LOOKBACK_DAYS = 420                     # 足夠暖機 MA60 + MACD26
_MAX_CONCURRENCY = 4                           # 免費版限流, 並發壓低
_REQUEST_GAP = 0.35                            # 每次請求後小睡 (秒)

BASE_VALUE = 100.0          # 指數基準點
MA_SHORT = 20
MA_LONG = 60
MACD_FAST = 12
MACD_SLOW = 26
NEUTRAL_BAND = 0.5          # MACD% 三色中性帶 (±%); 帶內視為均線密集→黃

_sema = asyncio.Semaphore(_MAX_CONCURRENCY)


async def _finmind_get(dataset: str, data_id: str, start_date: str) -> pd.DataFrame:
    """免費直連 FinMind (不帶 token); 失敗回空 DataFrame。"""
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


async def _fetch_close(code: str) -> pd.DataFrame:
    """回傳 date / close (非還原日線)。"""
    start = (datetime.today() - timedelta(days=_PRICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    df = await _finmind_get(_PRICE_DATASET, code, start)
    if df.empty or "close" not in df.columns:
        return pd.DataFrame()
    out = df[["date", "close"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna().sort_values("date").reset_index(drop=True)


def _roc_to_ts(s: str) -> pd.Timestamp | None:
    """民國日期字串 '1150625' → 2026-06-25。"""
    s = str(s).strip()
    if len(s) < 7:
        return None
    try:
        return pd.Timestamp(year=int(s[:-4]) + 1911, month=int(s[-4:-2]), day=int(s[-2:]))
    except Exception:
        return None


async def _fetch_twse_today() -> dict[str, tuple[pd.Timestamp, float]]:
    """一次拿 TWSE 全市場當日收盤; {code: (date, close)}。失敗回空 dict (不致命)。"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                _TWSE_DAY_ALL_URL,
                headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"},
            )
        rows = resp.json()
    except Exception:
        return {}
    out: dict[str, tuple[pd.Timestamp, float]] = {}
    for r in rows:
        code = r.get("Code")
        ts = _roc_to_ts(r.get("Date"))
        px = pd.to_numeric(str(r.get("ClosingPrice", "")).replace(",", ""), errors="coerce")
        if code and ts is not None and pd.notna(px) and px > 0:
            out[code] = (ts, float(px))
    return out


@dataclass(frozen=True)
class ConceptIndex:
    family: str
    description: str
    members: dict[str, str]          # {code: name}
    index_ew: pd.Series              # 等權重指數
    index_mcap: pd.Series            # 市值加權指數
    ma20_ew: pd.Series
    ma60_ew: pd.Series
    macd_pct: pd.Series              # 等權重指數的正規化 MACD%
    dropped: list[str]               # 抓不到價格、被剔除的成分股
    no_shares: list[str]             # 抓不到股本、未計入市值加權的成分股
    twse_appended: list[str]         # 用 TWSE 官方當日收盤補上最新一根的上市股


def _load_active_family(family: str | None) -> tuple[str, str, dict[str, str]]:
    """讀 concept_groups.json 的 active 區塊, 攤平子群成 {code: name}。"""
    if not _CONCEPT_PATH.exists():
        raise FileNotFoundError(f"找不到概念股清單: {_CONCEPT_PATH}")
    data = json.loads(_CONCEPT_PATH.read_text(encoding="utf-8"))
    active = data.get("active", {})
    if not active:
        raise ValueError("concept_groups.json 的 active 區塊是空的")

    name = family or next(iter(active))
    if name not in active:
        raise KeyError(f"active 裡沒有族群 '{name}', 可選: {list(active)}")

    fam = active[name]
    members: dict[str, str] = {}
    for sub in fam.get("subgroups", {}).values():
        for code, cn in sub.items():
            members[code] = cn
    return name, fam.get("description", ""), members


async def _fetch_shares(code: str) -> float:
    """回傳流通股數(相對尺度即可); 抓不到回 0。
    CapitalStock value 為股本(元), 面額10 → 股數 = 值 / 10。
    市值加權最終 rebase 到 100, 故只要各股股數尺度一致, 絕對值不影響權重。"""
    df = await _finmind_get(_BALANCE_DATASET, code, _BALANCE_LOOKBACK)
    if df.empty or "type" not in df.columns:
        return 0.0
    cap = df[df["type"] == "CapitalStock"]
    if cap.empty:
        return 0.0
    latest = cap.sort_values("date").iloc[-1]
    value = pd.to_numeric(latest.get("value"), errors="coerce")
    if pd.isna(value) or value <= 0:
        return 0.0
    return float(value) / 10.0


def _macd_pct(index: pd.Series) -> pd.Series:
    ema_fast = index.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = index.ewm(span=MACD_SLOW, adjust=False).mean()
    return (ema_fast - ema_slow) / ema_slow * 100.0


async def build_concept_index(family: str | None = None) -> ConceptIndex:
    name, desc, members = _load_active_family(family)
    codes = list(members)

    # 1) 並抓非還原日線 (semaphore 限流)
    price_tasks = [_fetch_close(c) for c in codes]
    price_results = await asyncio.gather(*price_tasks)

    close_cols: dict[str, pd.Series] = {}
    dropped: list[str] = []
    for code, df in zip(codes, price_results):
        if df is None or df.empty:
            dropped.append(code)
            continue
        s = df.set_index("date")["close"].astype(float)
        close_cols[code] = s[~s.index.duplicated(keep="last")]

    # 1b) TWSE 官方當日收盤補最新一根 (僅上市股; 比 FinMind 新才覆蓋)
    twse_today = await _fetch_twse_today()
    twse_appended: list[str] = []
    for code, s in list(close_cols.items()):
        hit = twse_today.get(code)
        if not hit:
            continue
        ts, px = hit
        if ts > s.index.max():
            s = pd.concat([s, pd.Series({ts: px})]).sort_index()
            close_cols[code] = s
            twse_appended.append(code)

    if len(close_cols) < 2:
        raise RuntimeError(
            f"有效成分股不足 2 檔 (抓到 {len(close_cols)}), 無法組指數。dropped={dropped}"
        )

    # 對齊日期: 用所有成分股都有資料的交集, 避免 rebase 基準日缺值
    price = pd.DataFrame(close_cols).dropna()
    if price.empty:
        # 交集為空 → 退而求其次, 用 union + 前向填補
        price = pd.DataFrame(close_cols).sort_index().ffill().dropna()
    if len(price) < MA_LONG + 5:
        raise RuntimeError(f"共同交易日僅 {len(price)} 天, 不足以算 MA{MA_LONG}")

    base_row = price.iloc[0]

    # 2) 等權重: 每檔 rebase→100 後取平均
    rebased = price.divide(base_row) * BASE_VALUE
    index_ew = rebased.mean(axis=1)

    # 3) 市值加權: 需股數
    share_tasks = [_fetch_shares(c) for c in price.columns]
    shares_list = await asyncio.gather(*share_tasks)
    shares = pd.Series(dict(zip(price.columns, shares_list)))
    no_shares = [c for c in price.columns if shares.get(c, 0) <= 0]
    valid = [c for c in price.columns if shares.get(c, 0) > 0]
    if len(valid) >= 2:
        mcap = price[valid].multiply(shares[valid], axis=1).sum(axis=1)
        index_mcap = mcap / mcap.iloc[0] * BASE_VALUE
    else:
        # 股數幾乎都抓不到 → 市值加權退回等權重, 並標記
        index_mcap = index_ew.copy()
        no_shares = list(price.columns)

    return ConceptIndex(
        family=name,
        description=desc,
        members={c: members[c] for c in price.columns},
        index_ew=index_ew,
        index_mcap=index_mcap,
        ma20_ew=index_ew.rolling(MA_SHORT).mean(),
        ma60_ew=index_ew.rolling(MA_LONG).mean(),
        macd_pct=_macd_pct(index_ew),
        dropped=dropped,
        no_shares=no_shares,
        twse_appended=twse_appended,
    )


def _macd_color(v: float) -> str:
    if v > NEUTRAL_BAND:
        return "#d62728"   # 紅: 偏多/乖離大
    if v < -NEUTRAL_BAND:
        return "#2ca02c"   # 綠: 偏空/乖離大向下
    return "#e6c200"       # 黃: 均線密集


def render_chart(ci: ConceptIndex, out_path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    # CJK 字型, 否則中文標題變方框
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )
    x = ci.index_ew.index

    ax1.plot(x, ci.index_ew, color="#1f77b4", lw=2.0, label="等權重指數")
    ax1.plot(x, ci.index_mcap, color="#7f7f7f", lw=1.4, ls="--", label="市值加權指數")
    ax1.plot(x, ci.ma20_ew, color="#ff7f0e", lw=1.2, label=f"MA{MA_SHORT}")
    ax1.plot(x, ci.ma60_ew, color="#9467bd", lw=1.2, label=f"MA{MA_LONG}")
    ax1.axhline(BASE_VALUE, color="#cccccc", lw=0.8, ls=":")
    ax1.set_title(f"{ci.family}　概念指數（基準=100，成分 {len(ci.members)} 檔）", fontsize=14)
    ax1.set_ylabel("指數")
    ax1.legend(loc="upper left", ncol=2, fontsize=9)
    ax1.grid(alpha=0.25)

    # 下方: 正規化 MACD% 三色長條
    colors = [_macd_color(v) for v in ci.macd_pct.fillna(0)]
    ax2.bar(x, ci.macd_pct.fillna(0), color=colors, width=1.0)
    ax2.axhline(0, color="#888888", lw=0.8)
    ax2.axhline(NEUTRAL_BAND, color="#dddddd", lw=0.6, ls="--")
    ax2.axhline(-NEUTRAL_BAND, color="#dddddd", lw=0.6, ls="--")
    ax2.set_ylabel("MACD%")
    ax2.yaxis.set_major_locator(MaxNLocator(5))
    ax2.grid(alpha=0.25)
    ax2.set_xlabel("日期")

    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _print_summary(ci: ConceptIndex) -> None:
    last = ci.index_ew.index[-1].date()
    ew = ci.index_ew.iloc[-1]
    mc = ci.index_mcap.iloc[-1]
    ma20 = ci.ma20_ew.iloc[-1]
    ma60 = ci.ma60_ew.iloc[-1]
    macd = ci.macd_pct.iloc[-1]
    tone = "紅(偏多)" if macd > NEUTRAL_BAND else ("綠(偏空)" if macd < -NEUTRAL_BAND else "黃(密集)")
    pos = "站上MA20" if ew > ma20 else ("跌破MA60" if ew < ma60 else "MA20~MA60之間")

    print(f"\n=== {ci.family} 概念指數  ({last}) ===")
    print(f"成分股 {len(ci.members)} 檔: " + " ".join(f"{c}{n}" for c, n in ci.members.items()))
    if ci.dropped:
        print(f"⚠️ 抓不到價格剔除: {ci.dropped}")
    if ci.no_shares:
        print(f"⚠️ 抓不到股本(未計入市值加權): {ci.no_shares}")
    if ci.twse_appended:
        print(f"🟢 TWSE 官方補當日收盤: {ci.twse_appended}")
    print(f"\n等權重指數 : {ew:7.2f}   (MA{MA_SHORT}={ma20:.2f}  MA{MA_LONG}={ma60:.2f}  →{pos})")
    print(f"市值加權指數: {mc:7.2f}")
    print(f"正規化MACD% : {macd:+.3f}   →{tone}")


def _list_families() -> list[str]:
    data = json.loads(_CONCEPT_PATH.read_text(encoding="utf-8"))
    return list(data.get("active", {}))


async def _run_one(family: str | None, make_chart: bool, out: str | None) -> None:
    ci = await build_concept_index(family)
    _print_summary(ci)
    if make_chart:
        safe = ci.family.replace("/", "_").replace("\\", "_")
        path = Path(out) if out else _PKG_ROOT.parent / f"_concept_{safe}.png"
        render_chart(ci, path)
        print(f"\n📈 圖已存: {path}")


async def _amain() -> None:
    parser = argparse.ArgumentParser(description="概念指數引擎")
    parser.add_argument("--family", default=None, help="active 裡的族群名 (預設第一個)")
    parser.add_argument("--all", action="store_true", help="一次算/畫 active 裡所有族群")
    parser.add_argument("--list", action="store_true", help="列出 active 所有族群名後結束")
    parser.add_argument("--no-chart", action="store_true", help="只印數字不畫圖")
    parser.add_argument("--out", default=None, help="圖片輸出路徑 (單一族群時)")
    args = parser.parse_args()

    if args.list:
        print("active 族群:")
        for f in _list_families():
            print(f"  - {f}")
        return

    if args.all:
        for fam in _list_families():
            try:
                await _run_one(fam, not args.no_chart, None)
            except Exception as e:
                print(f"\n⚠️ {fam} 失敗: {e}")
        return

    await _run_one(args.family, not args.no_chart, args.out)


if __name__ == "__main__":
    asyncio.run(_amain())
