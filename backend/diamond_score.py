"""鑽豹評鑒 — 財報 6 大面向評分，總分 15（LESSONS §2.13, 2026-06-10）。

評分設計（可量化規則，資料源 FinMind 免費 tier）：
  營收(0-3)：最新月YoY>0 ／ 近3月累計YoY>10% ／ 最新月營收創12個月新高
  毛利率(0-2)：QoQ 上升 ／ YoY 上升
  營業利益率(0-2)：QoQ 上升 ／ YoY 上升
  存貨(0-2)：QoQ 下降 ／ 存貨YoY增幅 < 營收YoY增幅（沒堆貨）
  合約負債(0-2)：⚠️ FinMind 免費版資產負債表無此欄（101 欄全查過）→ 恆為「無資料」0 分
  EBITDA利潤率(0-2)：QoQ 上升 ／ YoY 上升（EBITDA=營業利益+折舊+攤銷）
  自由現金流(0-2)：OCF>0(本業收到真錢，底線) ／ FCF>0(扣CAPEX仍有餘裕，加分)
                   → 擴產股(OCF+/FCF−)得1分不錯殺；只有本業失血(OCF−)才真扣分

高分（>= RECORD_THRESHOLD）自動記到 data/diamond_picks.json 供後續研究。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.finmind_chip import _fetch_dataset
from backend.finmind_fundamental import fetch_monthly_revenue
from backend.ticker_name import lookup as ticker_name

logger = logging.getLogger("diamond-score")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PICKS_PATH = _PROJECT_ROOT / "data" / "diamond_picks.json"

RECORD_THRESHOLD = 10   # 總分 >= 此值自動記入 picks
_STMT_LOOKBACK = 700    # 抓財報的天數（約 7 季，夠算 YoY）


@dataclass(frozen=True)
class ScoreItem:
    name: str
    got: float
    max: float
    note: str           # 細項說明（給訊息顯示）


@dataclass(frozen=True)
class DiamondResult:
    code: str
    name: str
    score: float
    max_score: float    # 固定 15
    items: tuple[ScoreItem, ...]
    recorded: bool      # 本次是否寫入 picks


# ── helpers ───────────────────────────────────────────────────────────────────

def _pivot(df: pd.DataFrame) -> pd.DataFrame:
    """FinMind long (date,type,value) → wide（index=季度日期）。"""
    if df.empty or "type" not in df.columns:
        return pd.DataFrame()
    out = df.pivot_table(index=df.index, columns="type", values="value", aggfunc="last")
    return out.sort_index()


def _col(df: pd.DataFrame, key: str) -> pd.Series:
    if df.empty or key not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[key], errors="coerce").dropna()


def _qoq_up(s: pd.Series) -> bool | None:
    if len(s) < 2:
        return None
    return bool(s.iloc[-1] > s.iloc[-2])


def _yoy_up(s: pd.Series) -> bool | None:
    if len(s) < 5:
        return None
    return bool(s.iloc[-1] > s.iloc[-5])


def _yoy_pct(s: pd.Series) -> float | None:
    if len(s) < 5 or s.iloc[-5] == 0:
        return None
    return float((s.iloc[-1] - s.iloc[-5]) / abs(s.iloc[-5]) * 100)


def _decum(s: pd.Series) -> pd.Series:
    """現金流量表是年內累計制（Q2=半年累計…），還原成單季值。

    同年內：本季 = 累計 - 上一季累計；每年第一筆 as-is。
    注意：若資料最舊一筆不是該年 Q1，該筆會偏大（只影響最舊一筆，近期比較不受影響）。
    """
    if s.empty:
        return s
    vals, prev_year, prev_val = [], None, 0.0
    for dt, v in s.items():
        vals.append(v - prev_val if prev_year == dt.year else v)
        prev_year, prev_val = dt.year, v
    return pd.Series(vals, index=s.index)


def _fmt_bool(v: bool | None, yes: str, no: str) -> str:
    if v is None:
        return "資料不足"
    return yes if v else no


# ── 各面向評分（pure functions）───────────────────────────────────────────────

def _score_revenue(mrev: pd.DataFrame, code: str | None = None) -> ScoreItem:
    if mrev.empty or "revenue" not in mrev.columns:
        return ScoreItem("營收", 0, 3, "無月營收資料")
    df = mrev.copy()
    y = df["revenue_year"] if "revenue_year" in df.columns else df.index.year
    m = df["revenue_month"] if "revenue_month" in df.columns else df.index.month
    df = df.assign(yy=pd.to_numeric(y), mm=pd.to_numeric(m))
    df = df.drop_duplicates(subset=["yy", "mm"], keep="last").sort_values(["yy", "mm"])
    rev = {(int(a), int(b)): float(c)
           for a, b, c in zip(df["yy"], df["mm"], df["revenue"])}
    keys = sorted(rev)
    if not keys:
        return ScoreItem("營收", 0, 3, "無月營收資料")
    ly, lm = keys[-1]

    pts, notes = 0, []
    last_yoy = None
    prev_key = (ly - 1, lm)
    if prev_key in rev and rev[prev_key] != 0:
        last_yoy = (rev[(ly, lm)] - rev[prev_key]) / abs(rev[prev_key]) * 100
        if last_yoy > 0:
            pts += 1
        notes.append(f"{lm}月YoY {last_yoy:+.1f}%")
        if last_yoy < 0 and code:               # 衰退才套淡旺季濾鏡（指標一）
            try:
                from backend.season import season_note
                sn = season_note(code, int(lm))
                if sn:
                    notes.append(sn)
            except Exception:
                pass
    else:
        notes.append("YoY缺對照月")

    cur3 = keys[-3:]
    prior3 = [(yy - 1, mm) for yy, mm in cur3]
    if len(cur3) == 3 and all(k in rev for k in prior3):
        c, p = sum(rev[k] for k in cur3), sum(rev[k] for k in prior3)
        if p != 0:
            g3 = (c - p) / abs(p) * 100
            if g3 > 10:
                pts += 1
            notes.append(f"近3月累計YoY {g3:+.1f}%")
    if len(keys) >= 12:
        last12 = [rev[k] for k in keys[-12:]]
        if rev[(ly, lm)] >= max(last12):
            pts += 1
            notes.append("創12月新高")
    return ScoreItem("營收", pts, 3, "、".join(notes))


def _score_margin(income: pd.DataFrame, num_key: str, label: str) -> ScoreItem:
    rev, num = _col(income, "Revenue"), _col(income, num_key)
    idx = rev.index.intersection(num.index)
    if len(idx) < 2:
        return ScoreItem(label, 0, 2, "資料不足")
    margin = (num.loc[idx] / rev.loc[idx].replace(0, pd.NA)).dropna() * 100
    pts = 0
    q, yy = _qoq_up(margin), _yoy_up(margin)
    if q:
        pts += 1
    if yy:
        pts += 1
    cur = f"{margin.iloc[-1]:.1f}%"
    return ScoreItem(label, pts, 2,
                     f"最新{cur}，QoQ{_fmt_bool(q,'↑','↓')}、YoY{_fmt_bool(yy,'↑','↓')}")


def _score_inventory(balance: pd.DataFrame, income: pd.DataFrame) -> ScoreItem:
    inv = _col(balance, "Inventories")
    if inv.empty:
        return ScoreItem("存貨", 0, 2, "無存貨資料（金融股等）")
    pts = 0
    q_down = None if len(inv) < 2 else bool(inv.iloc[-1] < inv.iloc[-2])
    if q_down:
        pts += 1
    inv_yoy, rev_yoy = _yoy_pct(inv), _yoy_pct(_col(income, "Revenue"))
    slower = None
    if inv_yoy is not None and rev_yoy is not None:
        slower = inv_yoy < rev_yoy
        if slower:
            pts += 1
    note = f"QoQ{_fmt_bool(q_down,'↓(佳)','↑')}"
    if inv_yoy is not None and rev_yoy is not None:
        note += f"、存貨YoY{inv_yoy:+.1f}% vs 營收YoY{rev_yoy:+.1f}%"
    return ScoreItem("存貨", pts, 2, note)


def _score_contract_liab() -> ScoreItem:
    return ScoreItem("合約負債", 0, 2, "FinMind免費版無此欄位（無資料）")


def _score_ebitda(income: pd.DataFrame, cashflow: pd.DataFrame) -> ScoreItem:
    rev, op = _col(income, "Revenue"), _col(income, "OperatingIncome")
    dep = _decum(_col(cashflow, "Depreciation"))
    amo = _decum(_col(cashflow, "AmortizationExpense"))
    idx = rev.index.intersection(op.index)
    if len(idx) < 2:
        return ScoreItem("EBITDA率", 0, 2, "資料不足")
    ebitda = op.loc[idx].copy()
    for extra in (dep, amo):
        if not extra.empty:
            ebitda = ebitda.add(extra.reindex(idx).fillna(0))
    margin = (ebitda / rev.loc[idx].replace(0, pd.NA)).dropna() * 100
    pts = 0
    q, yy = _qoq_up(margin), _yoy_up(margin)
    if q:
        pts += 1
    if yy:
        pts += 1
    return ScoreItem("EBITDA率", pts, 2,
                     f"最新{margin.iloc[-1]:.1f}%，QoQ{_fmt_bool(q,'↑','↓')}、YoY{_fmt_bool(yy,'↑','↓')}")


def _score_fcf(cashflow: pd.DataFrame) -> ScoreItem:
    """OCF 是底線、FCF 是加分（雷老闆心法.md 指標六：不一票否決擴產股）。

    計分：OCF>0 給 1 分（本業有收到真錢）＋ FCF>0 給 1 分（有自由餘裕）。
      🟢 OCF+/FCF+ = 2 分（又賺錢又有餘裕）
      🟡 OCF+/FCF− = 1 分（擴產期，本業正、CAPEX 大；不錯殺台燿這類）
      🔴 OCF−       = 0~?（本業失血才是真警訊）
    """
    ocf = _col(cashflow, "CashFlowsFromOperatingActivities")
    if ocf.empty:
        ocf = _col(cashflow, "NetCashInflowFromOperatingActivities")
    if ocf.empty:
        return ScoreItem("自由現金流", 0, 2, "無現金流資料")
    ocf = _decum(ocf)                                   # 累計制 → 單季
    capex = _decum(_col(cashflow, "PropertyAndPlantAndEquipment"))
    fcf = ocf - capex.reindex(ocf.index).fillna(0).abs()
    pts = 0
    ocf_pos = bool(ocf.iloc[-1] > 0)     # 底線：本業真的收到現金
    fcf_pos = bool(fcf.iloc[-1] > 0)     # 加分：扣掉 CAPEX 仍有餘裕
    if ocf_pos:
        pts += 1
    if fcf_pos:
        pts += 1
    if not ocf_pos:
        level = "🔴本業失血"
    elif not fcf_pos:
        level = "🟡擴產期"
    else:
        level = "🟢"
    cum4 = float(fcf.iloc[-4:].sum()) if len(fcf) >= 4 else None
    note = f"{level} OCF{'+' if ocf_pos else '−'}/FCF{'+' if fcf_pos else '−'}"
    if cum4 is not None:
        note += f"、近4季FCF累計 {cum4 / 1e8:,.0f} 億"   # 現金流量表單位＝元（2330 實測驗證）
    return ScoreItem("自由現金流", pts, 2, note)


# ── picks 持久化（原子寫入，比照 watchlist.py）────────────────────────────────

def load_picks() -> list[dict]:
    try:
        return json.loads(PICKS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning("diamond_picks.json read failed: %s", exc)
        return []


def _save_picks(picks: list[dict]) -> None:
    tmp = PICKS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(picks, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PICKS_PATH)


def _record_pick(result: "DiamondResult") -> None:
    picks = [p for p in load_picks() if p.get("code") != result.code]
    picks.append({
        "code": result.code,
        "name": result.name,
        "score": result.score,
        "max": result.max_score,
        "date": datetime.now().strftime("%Y-%m-%d"),
    })
    picks.sort(key=lambda p: p.get("score", 0), reverse=True)
    _save_picks(picks)


# ── public API ────────────────────────────────────────────────────────────────

async def evaluate(code: str) -> DiamondResult:
    """對單一股票跑鑽豹評鑒（4 個 FinMind 呼叫）。高分自動記錄。"""
    mrev = await fetch_monthly_revenue(code)
    income = _pivot(await _fetch_dataset(
        "TaiwanStockFinancialStatements", code, lookback_days=_STMT_LOOKBACK))
    balance = _pivot(await _fetch_dataset(
        "TaiwanStockBalanceSheet", code, lookback_days=_STMT_LOOKBACK))
    cashflow = _pivot(await _fetch_dataset(
        "TaiwanStockCashFlowsStatement", code, lookback_days=_STMT_LOOKBACK))

    items = (
        _score_revenue(mrev, code),
        _score_margin(income, "GrossProfit", "毛利率"),
        _score_margin(income, "OperatingIncome", "營業利益率"),
        _score_inventory(balance, income),
        _score_contract_liab(),
        _score_ebitda(income, cashflow),
        _score_fcf(cashflow),
    )
    score = float(sum(i.got for i in items))
    result = DiamondResult(
        code=code, name=ticker_name(code), score=score, max_score=15.0,
        items=items, recorded=False,
    )
    if score >= RECORD_THRESHOLD:
        try:
            _record_pick(result)
            result = replace(result, recorded=True)
        except Exception as exc:
            logger.warning("record pick failed: %s", exc)
    return result
