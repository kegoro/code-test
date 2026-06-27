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

# ── 逐字稿版（趨勢交易）新邏輯參數，供 /six 對照 ──────────────────────────────
NEW_MA_FAST, NEW_MA_SLOW = 50, 200    # ② 節奏線 / 大趨勢線
NEW_SLOPE_FAST, NEW_SLOPE_SLOW = 5, 20  # 兩條均線各自的上彎判斷窗
NEW_BB_STD = 2.0          # ③ 上軌 = 中軌 + 2σ（突破上軌才算）
NEW_FIB_KEYS = (0.382, 0.618)   # ④ 只認 38.2% / 61.8% 兩個關鍵位
NEW_FIB_TOL = 0.03        # ④ 關鍵位容差 ±3%
NEW_RSI_MID = 50.0        # ⑤ 50 為多空分界，回測企穩再上
NEW_MIN_BARS = NEW_MA_SLOW + 25  # 要算 MA200 + 上彎窗
TOP_N = 150              # 中大型活躍股：依今日成交值排序、只深掃前 N 檔（FinMind 免費匿名層上限保守值）
STRONG_PCT = 5.0         # 強勢股門檻：當日漲幅 ≥ 5%
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
    pct_change: float = 0.0  # 今日漲幅%（強勢股用；潛力股不計）


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


def _pct_change(close, change) -> float:
    """當日漲幅% = change /(close-change)*100；無法計算回 NaN。"""
    c, ch = _to_num(close), _to_num(change)
    prev = c - ch
    if pd.isna(c) or pd.isna(ch) or prev <= 0:
        return float("nan")
    return float(ch / prev * 100)


async def _fetch_twse_liquid() -> dict[str, tuple[str, float, float]]:
    """{code: (name, trade_value, pct)} 上市。"""
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.get(_TWSE_DAY_ALL_URL, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
        rows = r.json()
    except Exception:
        return {}
    out: dict[str, tuple[str, float, float]] = {}
    for d in rows:
        code = str(d.get("Code", "")).strip()
        tv = _to_num(d.get("TradeValue"))
        if _is_common_stock(code) and pd.notna(tv):
            pct = _pct_change(d.get("ClosingPrice"), d.get("Change"))
            out[code] = (str(d.get("Name", "")).strip(), float(tv), pct)
    return out


async def _fetch_tpex_liquid() -> dict[str, tuple[str, float, float]]:
    """{code: (name, trade_value, pct)} 上櫃。"""
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.get(_TPEX_DAILY_URL, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
        rows = r.json()
    except Exception:
        return {}
    out: dict[str, tuple[str, float, float]] = {}
    for d in rows:
        code = str(d.get("SecuritiesCompanyCode", "")).strip()
        tv = _to_num(d.get("TransactionAmount"))
        if _is_common_stock(code) and pd.notna(tv):
            pct = _pct_change(d.get("Close"), d.get("Change"))
            out[code] = (str(d.get("CompanyName", "")).strip(), float(tv), pct)
    return out


async def _build_universe(top_n: int, min_pct: float | None = None) -> tuple[list[tuple[str, str, float, float]], int]:
    """回傳 (依成交值排序的前 top_n 檔[code,name,trade_value,pct], 母體檔數)。

    min_pct 有給時先濾掉「當日漲幅 < min_pct」的，再依成交值排序取前 top_n（強勢股用）。
    """
    twse, tpex = await asyncio.gather(_fetch_twse_liquid(), _fetch_tpex_liquid())
    merged = {**twse, **tpex}
    items = list(merged.items())
    if min_pct is not None:
        items = [kv for kv in items if pd.notna(kv[1][2]) and kv[1][2] >= min_pct]
    ranked = sorted(items, key=lambda kv: kv[1][1], reverse=True)
    top = [(code, nm, tv, pct) for code, (nm, tv, pct) in ranked[:top_n]]
    return top, len(items)


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


async def _scan(min_score: int, min_pct: float | None) -> PotentialResult:
    """共用掃描核心：min_pct=None→活躍股(潛力股)；min_pct=5→強勢股。"""
    universe, total = await _build_universe(TOP_N, min_pct=min_pct)

    async def _one(code: str, name: str, tv: float, pct: float) -> PotentialCandidate | None:
        df = await _fetch_ohlcv(code)
        if df.empty:
            return None
        score, conds, rsi, fib, vr = _score_df(df)
        return PotentialCandidate(
            code=code, name=name, trade_value=tv, close=float(df["close"].iloc[-1]),
            score=score, conds=tuple(conds), rsi=rsi, fib_retr=fib, vol_ratio=vr,
            pct_change=(pct if pd.notna(pct) else 0.0),
        )

    results = await asyncio.gather(*[_one(c, n, tv, pct) for c, n, tv, pct in universe])
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


def _six_detail_lines(df: pd.DataFrame) -> tuple[int, list[str]]:
    """單檔逐條解說（命中與否 + 實際數字）。回傳 (score, 文字行list)。"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    score = 0
    out: list[str] = []

    def mk(ok: bool) -> str:
        nonlocal score
        if ok:
            score += 1
        return "✅" if ok else "▫️"

    # ① 量放大
    vol_ma = vol.rolling(MA_PERIOD).mean()
    vr = float(vol.iloc[-1] / vol_ma.iloc[-1]) if vol_ma.iloc[-1] > 0 else 0.0
    ok = vr >= VOL_MULT
    out.append(f"① 量放大 {mk(ok)} 今量 {vr:.1f}×20日均量（門檻 {VOL_MULT:g}×）")

    # ② 均線多頭
    ma = close.rolling(MA_PERIOD).mean()
    slope_up = ma.iloc[-1] > ma.iloc[-1 - SLOPE_LOOKBACK]
    above = close.iloc[-1] > ma.iloc[-1]
    ok = slope_up and above
    why = "MA20上彎且收盤站上" if ok else ("MA20上彎但收盤未站上" if slope_up else ("收盤站上但MA20未上彎" if above else "MA20走平/下彎且收盤在下"))
    out.append(f"② 均線多頭 {mk(ok)} {why}（收{close.iloc[-1]:.2f} / MA20 {ma.iloc[-1]:.2f}）")

    # ③ 布林開口
    std = close.rolling(MA_PERIOD).std()
    bw = (4 * std) / ma
    widen = bw.iloc[-1] > bw.iloc[-1 - BAND_LOOKBACK] * BAND_OPEN_RATIO
    ok = widen and above
    why = "帶寬放大且收盤在中軌上（突破中）" if ok else ("帶寬放大但收盤未過中軌" if widen else "帶寬未較5日前放大（仍收斂）")
    out.append(f"③ 布林開口 {mk(ok)} {why}")

    # ④ 斐波回調
    window = df.iloc[-FIB_LOOKBACK:]
    low_idx = window["low"].idxmin()
    after = window.loc[low_idx:]
    fib = float("nan")
    ok = False
    if len(after) >= 2:
        sl, sh = float(window["low"].min()), float(after["high"].max())
        if sh > sl:
            fib = (sh - close.iloc[-1]) / (sh - sl)
            ok = FIB_LOW - FIB_TOL <= fib <= FIB_HIGH + FIB_TOL
    fib_txt = f"回調 {fib*100:.0f}%" if fib == fib else "無有效波段"
    why = f"{fib_txt}（落在黃金區 38~62%）" if ok else (f"{fib_txt}（不在 38~62%）" if fib == fib else fib_txt)
    out.append(f"④ 斐波回調 {mk(ok)} {why}")

    # ⑤ RSI 止穩翻揚
    rsi = _rsi(close)
    in_band = RSI_LOW <= rsi.iloc[-1] <= RSI_HIGH
    rising = rsi.iloc[-1] > rsi.iloc[-2]
    ok = in_band and rising
    why = "在 45~60 止穩帶且翻揚" if ok else (f"RSI {rsi.iloc[-1]:.0f} 在帶內但未翻揚" if in_band else f"RSI {rsi.iloc[-1]:.0f} 不在 45~60 帶")
    out.append(f"⑤ RSI翻揚 {mk(ok)} {why}")

    # ⑥ MACD 金叉
    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = dif - dea
    ok = hist.iloc[-1] > 0 and hist.iloc[-1 - CROSS_WINDOW] < 0
    why = f"近 {CROSS_WINDOW} 日柱由負翻正（剛金叉）" if ok else ("柱已在零軸上（金叉已過）" if hist.iloc[-1] > 0 else "柱仍在零軸下（未金叉）")
    out.append(f"⑥ MACD金叉 {mk(ok)} {why}")

    return score, out


async def explain_six(code: str, name: str = "") -> str:
    """單檔六大技術特性逐項解說（供 /fin 附掛）。"""
    df = await _fetch_ohlcv(code)
    title = f"━━ 六大技術特性 {code} {name}".rstrip()
    if df.empty or len(df) < MIN_BARS:
        return f"{title} ━━\n資料不足（需 ≥{MIN_BARS} 根日線），略過"
    score, lines = _six_detail_lines(df)
    head = [f"{title} ━━", "（收盤級日線 / FinMind 免費非還原）", f"命中 {score}/6"]
    tail = ["", "③突破 vs ④拉回 互斥不會同時亮；中④=拉回找買點、中⑥=已啟動追勢"]
    return "\n".join(head + [""] + lines + tail)


# ── /six：現有版 vs 逐字稿版 逐模塊對照 ────────────────────────────────────

_SIX_NAMES = {1: "成交量", 2: "均線", 3: "布林帶", 4: "斐波回調", 5: "RSI", 6: "MACD"}


def _old_compact(df: pd.DataFrame) -> list[tuple[bool, str]]:
    """現有版 6 條：回傳每條 (命中, 短說明)。"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    res: list[tuple[bool, str]] = []

    vol_ma = vol.rolling(MA_PERIOD).mean()
    vr = float(vol.iloc[-1] / vol_ma.iloc[-1]) if vol_ma.iloc[-1] > 0 else 0.0
    res.append((vr >= VOL_MULT, f"今量 {vr:.1f}×20日均量（門檻 {VOL_MULT:g}×）"))

    ma = close.rolling(MA_PERIOD).mean()
    ok = ma.iloc[-1] > ma.iloc[-1 - SLOPE_LOOKBACK] and close.iloc[-1] > ma.iloc[-1]
    res.append((ok, f"MA20上彎且站上（收{close.iloc[-1]:.1f}/MA20 {ma.iloc[-1]:.1f}）"))

    std = close.rolling(MA_PERIOD).std()
    bw = (4 * std) / ma
    ok = bw.iloc[-1] > bw.iloc[-1 - BAND_LOOKBACK] * BAND_OPEN_RATIO and close.iloc[-1] > ma.iloc[-1]
    res.append((ok, "帶寬放大且收>中軌" if ok else "帶寬未放大/收未過中軌"))

    window = df.iloc[-FIB_LOOKBACK:]
    after = window.loc[window["low"].idxmin():]
    fib = float("nan")
    if len(after) >= 2:
        sl, sh = float(window["low"].min()), float(after["high"].max())
        if sh > sl:
            fib = (sh - close.iloc[-1]) / (sh - sl)
    ok = fib == fib and FIB_LOW - FIB_TOL <= fib <= FIB_HIGH + FIB_TOL
    res.append((ok, f"回調 {fib*100:.0f}%（認 33~67% 連續帶）" if fib == fib else "無有效波段"))

    rsi = _rsi(close)
    ok = RSI_LOW <= rsi.iloc[-1] <= RSI_HIGH and rsi.iloc[-1] > rsi.iloc[-2]
    res.append((ok, f"RSI {rsi.iloc[-1]:.0f}（認 45~60 且翻揚）"))

    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    hist = (ema_f - ema_s) - (ema_f - ema_s).ewm(span=MACD_SIGNAL, adjust=False).mean()
    ok = hist.iloc[-1] > 0 and hist.iloc[-1 - CROSS_WINDOW] < 0
    res.append((ok, f"近{CROSS_WINDOW}日柱由負翻正" if ok else "非近期剛翻正"))
    return res


def _new_compact(df: pd.DataFrame) -> list[tuple[bool, str]]:
    """逐字稿版（趨勢交易）6 模塊：回傳每條 (命中, 短說明)。"""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    n = len(df)
    res: list[tuple[bool, str]] = []

    # ① 量價配合：價漲 且 量增
    price_up = close.iloc[-1] > close.iloc[-2]
    vol_ma = vol.rolling(MA_PERIOD).mean()
    vol_up = vol.iloc[-1] > vol_ma.iloc[-1]
    ok = price_up and vol_up
    why = ("價漲且量增（大資金進場）" if ok
           else ("價漲但量縮（假動作）" if price_up else "今日收黑（無上漲可驗證）"))
    res.append((ok, why))

    # ② 雙均線多頭：站上 MA50 & MA200，且雙線上彎
    if n >= NEW_MA_SLOW + NEW_SLOPE_SLOW:
        ma_f = close.rolling(NEW_MA_FAST).mean()
        ma_s = close.rolling(NEW_MA_SLOW).mean()
        above = close.iloc[-1] > ma_f.iloc[-1] and close.iloc[-1] > ma_s.iloc[-1]
        up_f = ma_f.iloc[-1] > ma_f.iloc[-1 - NEW_SLOPE_FAST]
        up_s = ma_s.iloc[-1] > ma_s.iloc[-1 - NEW_SLOPE_SLOW]
        ok = above and up_f and up_s
        if ok:
            why = f"站上MA50({ma_f.iloc[-1]:.0f})、MA200({ma_s.iloc[-1]:.0f})且雙線上彎"
        elif not above:
            why = f"未同時站上MA50/MA200（收{close.iloc[-1]:.0f}）"
        else:
            why = "站上但MA50/MA200未同步上彎"
        res.append((ok, why))
    else:
        res.append((False, f"資料不足算MA200（需≥{NEW_MA_SLOW + NEW_SLOPE_SLOW}根）"))

    # ③ 布林開口 + 突破上軌（中+2σ）
    ma20 = close.rolling(MA_PERIOD).mean()
    std20 = close.rolling(MA_PERIOD).std()
    bw = (2 * NEW_BB_STD * std20) / ma20    # 上下軌間距/中軌
    upper = ma20 + NEW_BB_STD * std20
    opening = bw.iloc[-1] > bw.iloc[-1 - BAND_LOOKBACK]
    broke = close.iloc[-1] > upper.iloc[-1]
    ok = opening and broke
    why = ("開口且收盤突破上軌（爆發）" if ok
           else ("開口但未破上軌" if opening else "帶寬仍收斂（蓄積中）"))
    res.append((ok, why))

    # ④ 斐波貼近 38.2% 或 61.8% 關鍵位
    window = df.iloc[-FIB_LOOKBACK:]
    after = window.loc[window["low"].idxmin():]
    fib = float("nan")
    if len(after) >= 2:
        sl, sh = float(window["low"].min()), float(after["high"].max())
        if sh > sl:
            fib = (sh - close.iloc[-1]) / (sh - sl)
    near = fib == fib and any(abs(fib - k) <= NEW_FIB_TOL for k in NEW_FIB_KEYS)
    if fib == fib:
        why = f"回調 {fib*100:.0f}%（{'貼近' if near else '不貼近'} 38.2/61.8%）"
    else:
        why = "無有效波段"
    res.append((near, why))

    # ⑤ RSI 站上50、回測企穩再上彎
    rsi = _rsi(close)
    above50 = rsi.iloc[-1] > NEW_RSI_MID
    rising = rsi.iloc[-1] > rsi.iloc[-2]
    dipped = float(rsi.iloc[-5:].min()) <= NEW_RSI_MID + 5    # 近5日曾回測到~50
    ok = above50 and rising and dipped
    why = (f"RSI {rsi.iloc[-1]:.0f}＞50、回測企穩再上彎" if ok
           else (f"RSI {rsi.iloc[-1]:.0f}＞50但未見回測企穩翻揚" if above50 else f"RSI {rsi.iloc[-1]:.0f} 在50下方（多頭未掌控）"))
    res.append((ok, why))

    # ⑥ MACD 柱先縮短 → 金叉
    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    hist = (ema_f - ema_s) - (ema_f - ema_s).ewm(span=MACD_SIGNAL, adjust=False).mean()
    crossed = hist.iloc[-1] > 0 and float(hist.iloc[-1 - CROSS_WINDOW:-1].min()) < 0
    shrank = hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]    # 動能柱連續轉強
    ok = crossed and shrank
    why = ("空頭柱先縮短後金叉（點火）" if ok
           else ("已金叉但柱未見先縮短" if crossed else ("柱轉強但尚未金叉（預告）" if shrank else "未見縮短/金叉")))
    res.append((ok, why))
    return res


async def explain_six_compare(code: str, name: str = "") -> str:
    """/six：現有版 vs 逐字稿版 逐模塊對照。"""
    df = await _fetch_ohlcv(code)
    title = f"🔬 六大指標 新舊對照 {code} {name}".rstrip()
    if df.empty or len(df) < MIN_BARS:
        return f"{title}\n資料不足（需 ≥{MIN_BARS} 根日線），略過"
    old = _old_compact(df)
    new = _new_compact(df)
    os_, ns = sum(o for o, _ in old), sum(o for o, _ in new)
    mk = lambda b: "✅" if b else "▫️"
    lines = [
        title,
        "（收盤級日線 / FinMind；現有版＝量價剛發動篩選，逐字稿版＝趨勢交易進場）",
        f"合計　現有 {os_}/6 ｜ 逐字稿 {ns}/6",
        "",
    ]
    for i in range(6):
        lines.append(f"{COND_MARK[i+1]} {_SIX_NAMES[i+1]}")
        lines.append(f"   現有 {mk(old[i][0])} {old[i][1]}")
        lines.append(f"   逐字 {mk(new[i][0])} {new[i][1]}")
    lines.append("")
    lines.append("逐字稿版更嚴（雙均線50/200、突破上軌、貼關鍵位、需先縮量回測）→ 同檔通常分數較低但訊號更純")
    return "\n".join(lines)


async def scan(min_score: int = DEFAULT_MIN_SCORE) -> PotentialResult:
    """潛力股：全市場活躍股(成交值前 N) + 6 條件計分。"""
    return await _scan(min_score, min_pct=None)


async def scan_strong(min_score: int = DEFAULT_MIN_SCORE) -> PotentialResult:
    """強勢股：當日漲幅 ≥ STRONG_PCT% 的活躍股 + 6 條件計分。"""
    return await _scan(min_score, min_pct=STRONG_PCT)
