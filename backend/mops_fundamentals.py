# -*- coding: utf-8 -*-
"""MOPS 合併財報六大指標抓取(營收/毛利/營業利益/OCF/CAPEX/FCF)。

資料源:公開資訊觀測站 ajax_t164sb04(合併綜合損益表)/ ajax_t164sb05(合併現金流量表)。
回傳 UTF-8 HTML table,金額單位:仟元。改 co_id 可抓任一上市櫃個股。
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import requests
from bs4 import BeautifulSoup

_HEAD = {"User-Agent": "Mozilla/5.0"}
_BASE = "https://mopsov.twse.com.tw/mops/web/ajax_"
_TIMEOUT = 15  # 單次請求逾時(快速失敗,不讓使用者乾等)
_MAX_CODES = 3  # 一次最多查幾檔(避免 MOPS 限流)


@dataclass(frozen=True)
class YearMetrics:
    """單一年度六大指標(原始單位:仟元)。"""

    year: int
    revenue: float | None
    gross: float | None
    op_income: float | None
    ocf: float | None
    capex: float | None
    inventory: float | None = None
    contract_liab: float | None = None
    period_label: str | None = None  # 季度模式顯示用(如 "2025Q1");年度為 None
    eps: float | None = None  # 每股盈餘(元;美股為 USD/股)。台股為年度、美股為單季

    @property
    def fcf(self) -> float | None:
        if self.ocf is None or self.capex is None:
            return None
        return self.ocf + self.capex

    @property
    def gross_margin(self) -> float | None:
        if not self.revenue or self.gross is None:
            return None
        return self.gross / self.revenue * 100

    @property
    def op_margin(self) -> float | None:
        if not self.revenue or self.op_income is None:
            return None
        return self.op_income / self.revenue * 100

    @property
    def fcf_tier(self) -> str:
        """雷老闆心法 FCF 三級:🟢 OCF+FCF正 / 🟡 擴產(OCF正FCF負) / 🔴 OCF負。"""
        if self.ocf is None:
            return ""
        if self.ocf < 0:
            return "🔴"
        if self.fcf is not None and self.fcf < 0:
            return "🟡"
        return "🟢"


def _num(s: str) -> float | None:
    s = s.strip().replace(",", "").replace("\xa0", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not re.match(r"^-?\d+(\.\d+)?$", s):
        return None
    v = float(s)
    return -v if neg else v


def _post(report: str, co_id: str, roc_year: int) -> str:
    data = {
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
        "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
        "isnew": "false", "co_id": co_id, "year": str(roc_year), "season": "04",
    }
    r = requests.post(_BASE + report, data=data, headers=_HEAD, timeout=_TIMEOUT)
    r.encoding = "utf-8"
    return r.text


def _find_row(html: str, pred) -> float | None:
    """回傳第一個科目名符合 pred 的列的『本期金額』(名稱後第一個可解析數字)。"""
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not tds:
            continue
        name = tds[0].replace(" ", "").replace("　", "")
        if pred(name):
            for cell in tds[1:]:
                v = _num(cell)
                if v is not None:
                    return v
    return None


def _company_name(html: str) -> str | None:
    m = re.search(r"本資料由(.+?)公司提供", html)
    return m.group(1) if m else None


def _safe_result(fut) -> str:
    try:
        return fut.result(timeout=_TIMEOUT + 5)
    except Exception:
        return ""


def fetch(co_id: str, years: int = 5) -> tuple[str | None, list[YearMetrics]]:
    """並行抓 co_id 近 years 年合併財報六大指標。回 (公司名, [YearMetrics 由舊到新])。

    10 個請求同時發,總耗時≈單次(數秒),任一年抓不到就跳過、不卡整體。
    """
    cur_roc = date.today().year - 1911
    last = cur_roc - 1  # 最新已公布年報(去年)
    rocs = list(range(last, last - years, -1))
    with ThreadPoolExecutor(max_workers=3 * len(rocs)) as ex:
        is_futs = {roc: ex.submit(_post, "t164sb04", co_id, roc) for roc in rocs}
        cf_futs = {roc: ex.submit(_post, "t164sb05", co_id, roc) for roc in rocs}
        bs_futs = {roc: ex.submit(_post, "t164sb03", co_id, roc) for roc in rocs}
        is_html = {roc: _safe_result(f) for roc, f in is_futs.items()}
        cf_html = {roc: _safe_result(f) for roc, f in cf_futs.items()}
        bs_html = {roc: _safe_result(f) for roc, f in bs_futs.items()}

    name: str | None = None
    rows: list[YearMetrics] = []
    for roc in rocs:
        ih, ch = is_html.get(roc, ""), cf_html.get(roc, "")
        bh = bs_html.get(roc, "")
        if name is None and ih:
            name = _company_name(ih)
        rev = _find_row(ih, lambda n: n == "營業收入合計")
        gross = (_find_row(ih, lambda n: n.startswith("營業毛利") and "淨額" in n)
                 or _find_row(ih, lambda n: n.startswith("營業毛利")))
        op = _find_row(ih, lambda n: n.startswith("營業利益"))
        ocf = _find_row(ch, lambda n: "營業活動之淨現金" in n)
        capex = _find_row(ch, lambda n: "取得不動產" in n and "設備" in n)
        # 資產負債表:存貨(流動資產)、合約負債(流動負債;非預收款商業模式可能無此科目)
        inv = _find_row(bh, lambda n: n == "存貨")
        cl = _find_row(bh, lambda n: n.startswith("合約負債") and "非流動" not in n)
        # 基本每股盈餘(損益表最末;非仟元,本身就是元)
        eps = (_find_row(ih, lambda n: n.startswith("基本每股盈餘"))
               or _find_row(ih, lambda n: n == "每股盈餘"))
        if rev is None and ocf is None:
            continue  # 該年無合併財報,跳過
        rows.append(YearMetrics(roc + 1911, rev, gross, op, ocf, capex, inv, cl,
                                eps=eps))
    rows.sort(key=lambda m: m.year)
    return name, rows


def _yi(value: float | None) -> str:
    """仟元 → 億元字串(1 億 = 100,000 仟元)。"""
    return f"{value / 1e5:.1f}" if value is not None else "—"


def format_telegram(co_id: str, name: str | None, rows: list[YearMetrics]) -> str:
    if not rows:
        return f"📊 {co_id}:MOPS 查無合併財報資料(可能是新股/未編合併報表)"
    head = f"📊 {co_id} {name or ''} 六大指標(MOPS 官方,單位:億元)"
    lines = [head, "", "年度│營收│毛利率│營益率│EPS│FCF"]
    for m in rows:
        gm = f"{m.gross_margin:.0f}%" if m.gross_margin is not None else "—"
        om = f"{m.op_margin:.0f}%" if m.op_margin is not None else "—"
        eps = f"{m.eps:.2f}" if m.eps is not None else "—"
        fcf = f"{m.fcf_tier}{_yi(m.fcf)}" if m.fcf is not None else "—"
        lines.append(f"{m.year}│{_yi(m.revenue)}│{gm}│{om}│{eps}│{fcf}")
    lines.append("")
    lines.append("FCF三級:🟢OCF+FCF正 / 🟡擴產(OCF正FCF負) / 🔴OCF負")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "6442"
    nm, data = fetch(code)
    print(format_telegram(code, nm, data))
