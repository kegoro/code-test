# -*- coding: utf-8 -*-
"""美股族群對應 + 族群近期漲幅表現。

打 /fin amd → 認得 AMD 屬「運算晶片」族群、同族群有 NVDA/INTC/QCOM,
抓出來算近 5/20/60 交易日漲幅,排行 + 族群均值判讀「族群在不在風頭上」。

族群表為人工維護(美股無台股那種產業別 API),先 cover 使用者關心的主題,之後可擴。
漲幅資料源複用 diamond_blade3._fetch_us_daily(yfinance 日K)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("us_sectors")

# 族群 → (中文名, 成員 tickers;龍頭放第一個)
PEER_GROUPS: dict[str, tuple[str, list[str]]] = {
    "compute_chip": ("運算晶片(CPU/GPU)", ["NVDA", "AMD", "INTC", "QCOM"]),
    "asic_network": ("網通/ASIC 晶片", ["AVGO", "MRVL", "ANET"]),
    "memory": ("記憶體", ["MU", "WDC", "STX"]),
    "foundry": ("晶圓代工", ["TSM", "UMC", "GFS"]),
    "optical_cpo": ("光通訊/CPO", ["COHR", "LITE", "AAOI", "POET"]),
    "passive_mlcc": ("被動元件(MLCC)", ["VSH", "APH", "TEL"]),
    "datacenter_power": ("資料中心電源/散熱", ["VRT", "PWR", "ETN"]),
    "eda": ("EDA/IP", ["SNPS", "CDNS", "ARM"]),
}

# 漲幅觀察窗(交易日)
_WINDOWS = [5, 20, 60]


@dataclass(frozen=True)
class PeerPerf:
    ticker: str
    last: float
    rets: dict[int, float | None]  # window → 漲幅 %


def find_group(ticker: str) -> tuple[str, str, list[str]] | None:
    """回 (族群key, 族群中文名, 成員清單);找不到回 None。"""
    t = ticker.upper().strip()
    for key, (name, members) in PEER_GROUPS.items():
        if t in members:
            return key, name, members
    return None


def _ret(closes: list[float], n: int) -> float | None:
    if len(closes) <= n:
        return None
    base = closes[-1 - n]
    if base <= 0:
        return None
    return (closes[-1] / base - 1) * 100


def _perf(ticker: str) -> PeerPerf | None:
    from backend.diamond_blade3 import _fetch_us_daily
    rows = _fetch_us_daily(ticker.upper(), 120)
    closes = [float(r["close"]) for r in rows if r.get("close")]
    if not closes:
        return None
    return PeerPerf(ticker.upper(), closes[-1], {n: _ret(closes, n) for n in _WINDOWS})


def group_performance(members: list[str]) -> list[PeerPerf]:
    return [p for p in (_perf(t) for t in members) if p is not None]


def _avg(perfs: list[PeerPerf], n: int) -> float | None:
    vals = [p.rets[n] for p in perfs if p.rets.get(n) is not None]
    return sum(vals) / len(vals) if vals else None


def format_group_block(queried: str, group_name: str, perfs: list[PeerPerf]) -> str:
    """族群漲幅排行 Telegram 區塊。"""
    if not perfs:
        return f"🏷️ 族群:{group_name}(同族群漲幅抓取失敗)"
    queried = queried.upper()
    ranked = sorted(perfs, key=lambda p: (p.rets.get(20) is not None, p.rets.get(20) or -1e9),
                    reverse=True)
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 10

    def pct(v: float | None) -> str:
        return f"{v:+.1f}%" if v is not None else "—"

    lines = [f"🏷️ 族群:{group_name}  ← {queried} 屬此族群",
             "近期漲幅排行(近5日/20日/60日):"]
    for i, p in enumerate(ranked):
        tag = "  👈你查的" if p.ticker == queried else ""
        r = p.rets
        lines.append(f"  {medals[i]} {p.ticker:<5} "
                     f"{pct(r.get(5))} / {pct(r.get(20))} / {pct(r.get(60))}{tag}")

    a20, a60 = _avg(perfs, 20), _avg(perfs, 60)
    lines.append("")
    lines.append(f"族群均值:近20日 {pct(a20)}、近60日 {pct(a60)}")
    lines.append("  " + _heat(a20, a60))
    return "\n".join(lines)


def _heat(a20: float | None, a60: float | None) -> str:
    """族群熱度判讀。"""
    if a20 is None:
        return "資料不足,無法判讀族群熱度"
    if a20 > 10:
        return "🔥 族群近月明顯轉強 → 資金在追這個族群(風頭上)"
    if a20 > 0:
        base = a60 if a60 is not None else 0
        if base > a20:
            return "🟡 族群近月仍正但動能放緩 → 從高檔回落,別追最後一棒"
        return "🟢 族群近月走多 → 資金溫和流入"
    return "❄️ 族群近月翻黑 → 資金退潮,逆勢個股要更挑(基本面要硬)"


def analyze_group(ticker: str) -> str | None:
    """主入口:ticker 有族群就回漲幅區塊文字,否則 None。"""
    g = find_group(ticker)
    if not g:
        return None
    _, name, members = g
    perfs = group_performance(members)
    return format_group_block(ticker, name, perfs)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "AMD"
    out = analyze_group(code)
    print(out or f"{code}:不在已知族群清單")
