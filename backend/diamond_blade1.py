"""鑽豹第一刀 — 整理後第一支帶量長紅K 偵測（= 主力成本區 / 進場價 + 賺賠比）。

書上定義（《鑽豹三刀流》第3章 / 第二大腦 [[第一刀-進場價]]）：
  盤整收斂「之後」出現的第一支「帶量長紅K」= 主力進場成本區。
  操作：隔天進場、停損設紅K低點（約 -10% 內）、目標 +15~20%。
  紀律（[[紀律鐵則]] / LESSONS §2.7.4b）：不追高 —— 若現價已遠離紅K成本，視為錯過、不進。

用法：
    python -m backend.diamond_blade1 2330           # 指定股票代號
    python -m backend.diamond_blade1 2618 2603      # 多檔
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.diamond_blade3 import DEFAULT_TICKERS, _fetch_daily

logger = logging.getLogger("diamond_blade1")

# ── 偵測參數 ──────────────────────────────────────────────
VOL_MA = 20              # 量能均線視窗（天）
VOL_MULT = 1.5          # 帶量門檻：當日量 > 均量 × 此倍數
BODY_MIN_PCT = 3.5      # 長紅K 實體最小漲幅 %（(close-open)/open）
CLOSE_POS_MIN = 0.6     # 收盤需落在當日 K 棒 (low~high) 的上 40%（收盤有力）
CONSOLIDATION_DAYS = 15  # 紅K「之前」盤整觀察天數
CONSOLIDATION_MAX_RANGE = 15.0  # 盤整段振幅上限 %（(max-min)/min）
LOOKBACK = 12           # 只在最近 N 日內找紅K（太久遠的成本區已失效）
STOP_MAX_PCT = 10.0     # 停損上限 %（雷老闆：約 10%）
TARGET_PCT = 18.0       # 目標報酬 %（雷老闆 15~20% 取中）
NEAR_COST_PCT = 5.0     # 現價在成本 +N% 內 = 仍可考慮進場（不追高）


@dataclass(frozen=True)
class Blade1:
    code: str
    name: str
    ok: bool
    msg: str = ""
    last: float = 0.0
    signal: bool = False        # 主力成本未破 = 第一刀訊號仍有效
    days_ago: int = -1          # 紅K 距今幾個交易日
    red_date: str = ""
    red_open: float = 0.0
    red_close: float = 0.0
    red_low: float = 0.0
    red_high: float = 0.0
    vol_ratio: float = 0.0      # 當日量 / 均量
    body_pct: float = 0.0       # 紅K 實體漲幅 %
    breakout: bool = False      # 是否同時突破盤整高點
    entry: float = 0.0          # 建議進場參考（紅K 收盤）
    stop: float = 0.0           # 停損（紅K 低點，限 -10% 內）
    target: float = 0.0         # 目標
    rr: float = 0.0             # 賺賠比 reward/risk
    status: str = ""            # 現價相對主力成本的判讀（含紀律）


def _analyze(code: str, name: str) -> Blade1:
    rows = _fetch_daily(code, days=150)
    floor = max(VOL_MA, CONSOLIDATION_DAYS)
    if len(rows) < floor + 5:
        return Blade1(code, name, False, "資料不足")

    o = [float(r["open"]) for r in rows]
    h = [float(r["max"]) for r in rows]
    lo = [float(r["min"]) for r in rows]
    c = [float(r["close"]) for r in rows]
    v = [float(r.get("Trading_Volume", 0) or 0) for r in rows]
    d = [str(r["date"]) for r in rows]
    n = len(rows)
    last = c[-1]

    found: int | None = None
    fb = fv = 0.0
    fbreak = False
    for i in range(n - 1, max(n - 1 - LOOKBACK, floor) - 1, -1):
        if o[i] <= 0:
            continue
        body_pct = (c[i] - o[i]) / o[i] * 100
        rng = h[i] - lo[i]
        close_pos = (c[i] - lo[i]) / rng if rng > 0 else 0.0
        vol_ma = sum(v[i - VOL_MA:i]) / VOL_MA if i >= VOL_MA else 0.0
        vol_ratio = v[i] / vol_ma if vol_ma > 0 else 0.0
        seg_h = max(h[i - CONSOLIDATION_DAYS:i])
        seg_l = min(lo[i - CONSOLIDATION_DAYS:i])
        seg_range = (seg_h - seg_l) / seg_l * 100 if seg_l > 0 else 999.0

        is_red = c[i] > o[i] and body_pct >= BODY_MIN_PCT and close_pos >= CLOSE_POS_MIN
        is_vol = vol_ratio >= VOL_MULT
        is_consolidated = seg_range <= CONSOLIDATION_MAX_RANGE
        breakout = c[i] >= seg_h
        if is_red and is_vol and (is_consolidated or breakout):
            found, fb, fv, fbreak = i, body_pct, vol_ratio, breakout
            break

    if found is None:
        return Blade1(code, name, True, "近期無帶量長紅K（無第一刀訊號，等待）",
                      last=last, signal=False)

    i = found
    entry = c[i]
    red_low = lo[i]
    stop = max(red_low, entry * (1 - STOP_MAX_PCT / 100))  # 紅K低點，但不深於 -10%
    target = entry * (1 + TARGET_PCT / 100)
    risk = entry - stop
    reward = target - entry
    rr = reward / risk if risk > 0 else 0.0
    days_ago = n - 1 - i

    if last < red_low:
        status = "⚠️ 已跌破主力成本（紅K低點）→ 第一刀失效，別進"
        signal = False
    elif last <= entry * (1 + NEAR_COST_PCT / 100):
        status = f"✅ 現價仍在成本區（+{(last / entry - 1) * 100:.1f}%）→ 守紀律可考慮進場"
        signal = True
    else:
        status = f"⚠️ 現價已離成本 +{(last / entry - 1) * 100:.1f}% → 追高違反紀律，等回測"
        signal = True

    return Blade1(
        code, name, True, "", last=last, signal=signal, days_ago=days_ago,
        red_date=d[i], red_open=o[i], red_close=c[i], red_low=red_low, red_high=h[i],
        vol_ratio=fv, body_pct=fb, breakout=fbreak,
        entry=entry, stop=stop, target=target, rr=rr, status=status,
    )


def _fmt(r: Blade1) -> str:
    if not r.ok:
        return f"🗡️ {r.code} {r.name}：{r.msg}"
    if not r.red_date:
        return f"🗡️ {r.code} {r.name}  收={r.last:.1f}  第一刀 ❌ {r.msg}"
    return (
        f"🗡️ {r.code} {r.name}  收={r.last:.1f}  第一刀 ✅（{r.days_ago} 日前帶量長紅K）\n"
        f"  紅K {r.red_date}：開{r.red_open:.1f}→收{r.red_close:.1f}"
        f"（實體+{r.body_pct:.1f}%、量{r.vol_ratio:.1f}倍{'、突破盤整' if r.breakout else ''}）\n"
        f"  主力成本區≈{r.red_low:.1f}~{r.red_close:.1f}\n"
        f"  進場≈{r.entry:.1f} 停損{r.stop:.1f} 目標{r.target:.1f}（賺賠比 {r.rr:.1f}）\n"
        f"  {r.status}"
    )


def run(tickers: dict[str, str]) -> str:
    lines = ["🗡️ 鑽豹第一刀 — 整理後第一支帶量長紅K（主力成本/進場價）\n"]
    for code, name in tickers.items():
        lines.append(_fmt(_analyze(code, name)))
        lines.append("")
    lines.append("⚠️ 第一刀 = 找「買在哪」；需配第二刀(基本面)、第三刀(技術加碼)")
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("codes", nargs="*", help="股票代號（留空用預設清單）")
    parser.add_argument("--tg", action="store_true", help="推送 Telegram")
    args = parser.parse_args()

    tickers = {c: DEFAULT_TICKERS.get(c, c) for c in args.codes} if args.codes else DEFAULT_TICKERS
    report = run(tickers)
    print(report)
    if args.tg:
        import asyncio
        from backend.daily_signal import _send_telegram
        asyncio.run(_send_telegram(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
