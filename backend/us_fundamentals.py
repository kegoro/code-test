# -*- coding: utf-8 -*-
"""美股六大指標抓取(營收/毛利/營業利益/OCF/CAPEX/FCF)+ 合約負債。

資料源(2026-06 改為 SEC 為主):
  - SEC EDGAR companyfacts(XBRL):官方、免費、歷史完整,主資料源。
    損益表/現金流在 10-Q 為 YTD 累計,_duration_quarterly() 還原為單季;
    Q4 單季由 10-K 全年值減去前三季得出。資產負債表(存貨/合約負債)為時點值。
  - yfinance:SEC 查無資料時的後備(免費季報約只回最近 7 季)。

預設抓「季度」(period='quarter')。SEC 可回溯多年,打破 yfinance「只有 7 季」限制。
回傳與 `mops_fundamentals.YearMetrics` 相容,可直接餵進 `diamond_full`。
金額單位:百萬美元(USD millions),顯示走 `usd()`。
CAPEX 約定:存成負值(與 YearMetrics.fcf = ocf + capex 相容)。
"""
from __future__ import annotations

import logging
import math
import os
from datetime import date

import requests

from backend.mops_fundamentals import YearMetrics

logger = logging.getLogger("us_fundamentals")

_TIMEOUT = 20
_SEC_CONTACT = os.getenv("SEC_CONTACT", "market-brain@example.com")
_SEC_UA = {"User-Agent": f"ray-smc-market-brain/1.0 ({_SEC_CONTACT})"}
_cik_cache: dict[str, int] = {}
_facts_cache: dict[str, dict] = {}  # ticker → us-gaap facts node
_name_cache: dict[str, str] = {}    # ticker → entityName

# us-gaap 概念候選(依序取第一個有資料的)
_C_REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax",
              "RevenueFromContractWithCustomerIncludingAssessedTax",
              "Revenues", "SalesRevenueNet"]
_C_GROSS = ["GrossProfit"]
_C_COR = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]
_C_OPINC = ["OperatingIncomeLoss"]
_C_OCF = ["NetCashProvidedByUsedInOperatingActivities",
          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
_C_CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets"]
_C_INV = ["InventoryNet"]
_C_CL = ["ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiability",
         "DeferredRevenueCurrent"]
_C_EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]  # 單位 USD/shares


# ── 顯示 ──────────────────────────────────────────────────────────────────
def usd(v: float | None) -> str:
    """百萬美元 → 人類可讀($B 大於十億,否則 $M)。"""
    if v is None:
        return "—"
    b = v / 1000
    return f"${b:,.1f}B" if abs(b) >= 1 else f"${v:,.0f}M"


def _qlabel(d: date) -> str:
    """季末日 → 日曆季標籤(2026-03-31 → 2026Q1)。"""
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


# ── yfinance 取數 ─────────────────────────────────────────────────────────
def _find_row(df, candidates: list[str]):
    """在財報 DataFrame 的 index 找符合的科目列(先精確、後包含,皆忽略大小寫)。"""
    if df is None or getattr(df, "empty", True):
        return None
    idx = list(df.index)
    low = {str(i).lower(): i for i in idx}
    for cand in candidates:
        key = cand.lower()
        if key in low:
            return df.loc[low[key]]
    for cand in candidates:
        key = cand.lower()
        for i in idx:
            if key in str(i).lower():
                return df.loc[i]
    return None


def _series(df, candidates: list[str], scale: float = 1e6) -> dict[date, float]:
    """抽出某科目逐期值(期末日 → 值/scale;金額用 1e6 轉百萬,EPS 用 1 不縮放)。"""
    row = _find_row(df, candidates)
    if row is None:
        return {}
    out: dict[date, float] = {}
    for col, val in row.items():
        d = getattr(col, "date", None)
        d = d() if callable(d) else None
        if d is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if math.isnan(f):
            continue
        out[d] = f / scale
    return out


def _name(tk) -> str | None:
    try:
        info = tk.get_info() if hasattr(tk, "get_info") else tk.info
        return info.get("shortName") or info.get("longName")
    except Exception:
        return None


def fetch(ticker: str, periods: int = 8,
          period: str = "quarter") -> tuple[str | None, list[YearMetrics]]:
    """抓美股近 periods 期(預設季度)六大指標 + 合約負債。

    回 (公司名, [YearMetrics 由舊到新])。period='quarter' 用季報、'annual' 用年報。
    SEC EDGAR 為主資料源;SEC 查無資料才退回 yfinance。
    """
    ticker = ticker.upper().strip()
    name, rows = fetch_sec(ticker, periods=periods, period=period)
    if rows:
        return name, rows
    logger.info("SEC 查無 %s,退回 yfinance", ticker)
    return _fetch_yfinance(ticker, periods=periods, period=period)


def _fetch_yfinance(ticker: str, periods: int = 8,
                    period: str = "quarter") -> tuple[str | None, list[YearMetrics]]:
    """yfinance 後備路徑(SEC 無資料時)。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安裝")
        return None, []

    q = period == "quarter"
    try:
        tk = yf.Ticker(ticker)
        inc = getattr(tk, "quarterly_income_stmt" if q else "income_stmt", None)
        if inc is None or getattr(inc, "empty", True):
            inc = getattr(tk, "quarterly_financials" if q else "financials", None)
        bs = getattr(tk, "quarterly_balance_sheet" if q else "balance_sheet", None)
        cf = getattr(tk, "quarterly_cashflow" if q else "cashflow", None)
    except Exception as exc:
        logger.warning("yfinance fetch %s 失敗: %s", ticker, exc)
        return None, []

    rev = _series(inc, ["Total Revenue", "Operating Revenue"])
    if not rev:
        return _name_safe(tk), []
    gross = _series(inc, ["Gross Profit"])
    cor = _series(inc, ["Cost Of Revenue", "Cost Of Revenue Total"])
    op = _series(inc, ["Operating Income", "Operating Income Or Loss"])
    ocf = _series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities",
                       "Cash Flow From Continuing Operating Activities"])
    capex = _series(cf, ["Capital Expenditure", "Capital Expenditures",
                         "Purchase Of PPE"])
    inv = _series(bs, ["Inventory"])
    cl = _series(bs, ["Current Deferred Revenue", "Deferred Revenue",
                      "Current Deferred Liabilities"])
    if not cl:
        cl = _edgar_contract_liab(ticker)
    eps = _series(inc, ["Diluted EPS", "Basic EPS"], scale=1)

    sel = sorted(rev.keys())[-periods:]
    rows: list[YearMetrics] = []
    for d in sel:
        g = gross.get(d)
        if g is None and d in rev and d in cor:
            g = rev[d] - abs(cor[d])
        rows.append(YearMetrics(
            year=d.year, revenue=rev.get(d), gross=g, op_income=op.get(d),
            ocf=ocf.get(d), capex=capex.get(d),
            inventory=inv.get(d), contract_liab=_nearest(cl, d),
            period_label=_qlabel(d) if q else None, eps=eps.get(d),
        ))
    return _name(tk), rows


def _nearest(series: dict[date, float], target: date, tol_days: int = 20) -> float | None:
    """取最接近 target 期末日的值(±tol_days 內);EDGAR/yfinance 季末日可能差幾天。"""
    if not series:
        return None
    if target in series:
        return series[target]
    best, best_gap = None, tol_days + 1
    for d, v in series.items():
        gap = abs((d - target).days)
        if gap < best_gap:
            best, best_gap = v, gap
    return best


def _name_safe(tk) -> str | None:
    try:
        return _name(tk)
    except Exception:
        return None


# ── SEC EDGAR 主力抓取 ────────────────────────────────────────────────────
def _cik(ticker: str) -> int | None:
    if not _cik_cache:
        try:
            r = requests.get("https://www.sec.gov/files/company_tickers.json",
                             headers=_SEC_UA, timeout=_TIMEOUT)
            for v in r.json().values():
                _cik_cache[str(v["ticker"]).upper()] = int(v["cik_str"])
        except Exception as exc:
            logger.warning("EDGAR ticker map 失敗: %s", exc)
            return None
    return _cik_cache.get(ticker.upper())


def _edgar_facts(ticker: str) -> dict:
    """抓 companyfacts 的 us-gaap node(每 ticker 快取一次)。失敗回 {}。"""
    key = ticker.upper()
    if key in _facts_cache:
        return _facts_cache[key]
    node: dict = {}
    try:
        cik = _cik(ticker)
        if cik:
            r = requests.get(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                headers=_SEC_UA, timeout=_TIMEOUT)
            data = r.json()
            node = data.get("facts", {}).get("us-gaap", {}) or {}
            if data.get("entityName"):
                _name_cache[key] = str(data["entityName"]).strip()
    except Exception as exc:
        logger.warning("EDGAR companyfacts %s 失敗: %s", ticker, exc)
    _facts_cache[key] = node
    return node


def _pick(gaap: dict, concepts: list[str]) -> dict | None:
    """回第一個有資料的概念 node。"""
    for c in concepts:
        node = gaap.get(c)
        if node and node.get("units", {}).get("USD"):
            return node
    return None


def _dedup_usd(node: dict | None) -> dict[tuple, float]:
    """收 10-K/10-Q 的 USD 筆,以 (start,end) 或 end 為 key,後申報覆蓋先申報。"""
    seen: dict[tuple, float] = {}
    if not node:
        return seen
    for it in node.get("units", {}).get("USD", []):
        form = str(it.get("form", ""))
        if not (form.startswith("10-K") or form.startswith("10-Q")):
            continue
        end = it.get("end")
        if not end:
            continue
        try:
            ed = date.fromisoformat(end)
            val = float(it["val"])
        except (ValueError, TypeError, KeyError):
            continue
        start = it.get("start")
        sd = None
        if start:
            try:
                sd = date.fromisoformat(start)
            except ValueError:
                sd = None
        seen[(sd, ed)] = val  # list 大致按申報序,後到覆蓋
    return seen


def _duration_quarterly(node: dict | None) -> dict[date, float]:
    """duration 概念(損益/現金流)→ 單季值(期末日 → 百萬美元)。

    10-Q 損益/現金流多為 YTD 累計(現金流甚至「只」報累計)。做法:依起始日分組
    (同 start = 同一條累計線),組內按期末日排序,相鄰相減得單季增量;只在該增量
    對應約一季(80~100 天)時採用。此法自動涵蓋:
      Q1=累計Q1、Q2=累計H1−Q1、Q3=累計9M−H1、Q4=全年(10-K)−累計9M。
    """
    seen = _dedup_usd(node)
    groups: dict[date, list[tuple[date, float]]] = {}
    for (sd, ed), v in seen.items():
        if sd is None:
            continue
        groups.setdefault(sd, []).append((ed, v))
    quarterly: dict[date, float] = {}
    for sd, lst in groups.items():
        lst.sort()
        prev_end, prev_val = sd, 0.0
        for ed, v in lst:
            seg_days = (ed - prev_end).days
            if 80 <= seg_days <= 100:
                quarterly[ed] = (v - prev_val) / 1e6  # 單季增量
            prev_end, prev_val = ed, v
    return quarterly


def _instant_series(node: dict | None) -> dict[date, float]:
    """instant 概念(資產負債表)→ 逐期末值(期末日 → 百萬美元)。"""
    return {ed: v / 1e6 for (sd, ed), v in _dedup_usd(node).items()}


def _pick_eps(gaap: dict) -> dict | None:
    """EPS 概念 node(單位 USD/shares,非 USD)。"""
    for c in _C_EPS:
        node = gaap.get(c)
        if node and node.get("units", {}).get("USD/shares"):
            return node
    return None


def _eps_series(node: dict | None, quarterly: bool) -> dict[date, float]:
    """EPS(USD/shares)逐期值(期末日 → 元/股)。

    EPS 不可乘 1e6、亦不做累計相減:直接挑出符合長度的 duration 筆
    (季 ≈ 80~100 天、年 ≈ 330~400 天),後申報覆蓋先申報。Q4 單季 XBRL 常缺,缺則略。
    """
    if not node:
        return {}
    lo, hi = (80, 100) if quarterly else (330, 400)
    out: dict[date, float] = {}
    for it in node.get("units", {}).get("USD/shares", []):
        form = str(it.get("form", ""))
        if not (form.startswith("10-K") or form.startswith("10-Q")):
            continue
        start, end = it.get("start"), it.get("end")
        if not (start and end):
            continue
        try:
            sd, ed = date.fromisoformat(start), date.fromisoformat(end)
            val = float(it["val"])
        except (ValueError, TypeError, KeyError):
            continue
        if lo <= (ed - sd).days <= hi:
            out[ed] = val  # list 大致按申報序,後到覆蓋
    return out


def fetch_sec(ticker: str, periods: int = 8,
              period: str = "quarter") -> tuple[str | None, list[YearMetrics]]:
    """SEC XBRL 主力抓取。回 (公司名, [YearMetrics 由舊到新]);無資料回 (名,[])。"""
    ticker = ticker.upper().strip()
    gaap = _edgar_facts(ticker)
    if not gaap:
        return None, []

    q = period == "quarter"
    pick = _duration_quarterly if q else _annual_duration
    rev = pick(_pick(gaap, _C_REVENUE))
    if not rev:
        return _edgar_name(ticker), []
    gross = pick(_pick(gaap, _C_GROSS))
    cor = pick(_pick(gaap, _C_COR))
    op = pick(_pick(gaap, _C_OPINC))
    ocf = pick(_pick(gaap, _C_OCF))
    capex = pick(_pick(gaap, _C_CAPEX))
    inv = _instant_series(_pick(gaap, _C_INV))
    cl = _instant_series(_pick(gaap, _C_CL))
    eps = _eps_series(_pick_eps(gaap), q)

    sel = sorted(rev.keys())[-periods:]
    rows: list[YearMetrics] = []
    for d in sel:
        g = gross.get(d)
        if g is None and d in rev and d in cor:
            g = rev[d] - abs(cor[d])
        cx = capex.get(d)
        rows.append(YearMetrics(
            year=d.year, revenue=rev.get(d), gross=g, op_income=op.get(d),
            ocf=ocf.get(d), capex=(-abs(cx) if cx is not None else None),
            inventory=_nearest(inv, d), contract_liab=_nearest(cl, d),
            period_label=_qlabel(d) if q else None,
            eps=_nearest(eps, d, tol_days=5),
        ))
    return _edgar_name(ticker), rows


def _annual_duration(node: dict | None) -> dict[date, float]:
    """duration 概念 → 年度值(取 ~全年 330~400 天的筆,期末日 → 百萬美元)。"""
    out: dict[date, float] = {}
    for (sd, ed), v in _dedup_usd(node).items():
        if sd is None:
            continue
        if 330 <= (ed - sd).days <= 400:
            out[ed] = v / 1e6
    return out


def _edgar_name(ticker: str) -> str | None:
    """companyfacts 的 entityName(_edgar_facts 抓取時已快取)。"""
    return _name_cache.get(ticker.upper())


def _edgar_contract_liab(ticker: str) -> dict[date, float]:
    """SEC XBRL 合約負債逐期值(期末日 → 百萬美元)。yfinance 後備路徑用。"""
    return _instant_series(_pick(_edgar_facts(ticker), _C_CL))


def fetch_valuation(ticker: str) -> dict[str, float | None]:
    """美股估值快照(yfinance info):本益比/前瞻PE/TTM EPS/現價。失敗回 {}。"""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    try:
        tk = yf.Ticker(ticker.upper().strip())
        info = tk.get_info() if hasattr(tk, "get_info") else tk.info
    except Exception as exc:
        logger.warning("yfinance valuation %s 失敗: %s", ticker, exc)
        return {}
    return {
        "pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps_ttm": info.get("trailingEps"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }


# ── Telegram 輸出 ─────────────────────────────────────────────────────────
def format_telegram(ticker: str, name: str | None, rows: list[YearMetrics]) -> str:
    if not rows:
        return f"📊 {ticker}:查無美股財報(yfinance/EDGAR 無資料,確認代號)"
    quarterly = any(m.period_label for m in rows)
    unit = "季,單位:USD" if quarterly else "單位:USD"
    head = f"📊 {ticker} {name or ''} 六大指標(SEC XBRL,{unit})"
    col = "季別" if quarterly else "年度"
    lines = [head, "", f"{col}│營收│毛利率│營益率│EPS│FCF"]
    for m in rows:
        gm = f"{m.gross_margin:.0f}%" if m.gross_margin is not None else "—"
        om = f"{m.op_margin:.0f}%" if m.op_margin is not None else "—"
        eps = f"${m.eps:.2f}" if m.eps is not None else "—"
        fcf = f"{m.fcf_tier}{usd(m.fcf)}" if m.fcf is not None else "—"
        label = m.period_label or m.year
        lines.append(f"{label}│{usd(m.revenue)}│{gm}│{om}│{eps}│{fcf}")
    lines += [
        "",
        "FCF三級:🟢OCF+FCF正 / 🟡擴產(OCF正FCF負) / 🔴OCF負",
        "合約負債=Deferred Revenue / ASC606 ContractLiability(SEC XBRL)",
    ]
    if quarterly:
        lines.append("資料源 SEC EDGAR(XBRL),可回溯多年;Q4 由 10-K 全年減前三季")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "IREN"
    nm, data = fetch(code)
    print(format_telegram(code, nm, data))
