"""鑽豹第三刀 — 技術面三指標檢核（均線多頭排列 / MACD 黃金交叉 / 乖離率黃金交叉）。

書上定義（《鑽豹三刀流》第3章）：
  1. 均線多頭排列：越短期均線在越上面（MA5>MA10>MA20>MA60），且股價站上 MA5
  2. MACD 黃金交叉：DIF(快線) 向上突破 MACD(慢線)，柱狀體翻正在零軸上方
  3. 乖離率黃金交叉：短期乖離率平均線向上突破長期乖離率平均線，且當天乖離率為正

用法：
    python -m backend.diamond_blade3                 # 跑預設標的清單
    python -m backend.diamond_blade3 2618 2603 6274  # 指定股票代號
    python -m backend.diamond_blade3 --tg            # 結果推 Telegram
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
logger = logging.getLogger("diamond_blade3")

_TOKEN = (os.getenv("FINMIND_TOKEN") or os.getenv("FINMIND_API_TOKEN") or "")

# 預設標的：航空 + 航運 + 銅箔基板（前面分析過的批次）
DEFAULT_TICKERS = {
    "2610": "華航",   "2618": "長榮航", "2646": "星宇",   "6757": "台灣虎航",
    "2603": "長榮",   "2609": "陽明",   "2615": "萬海",
    "6274": "台燿",
}

# 乖離率參數
BIAS_SHORT = 6     # 短期乖離率
BIAS_LONG  = 24    # 長期乖離率平均線視窗


def _is_us(code: str) -> bool:
    """含英文字母 = 美股 ticker(台股代號純數字)。"""
    return any(ch.isalpha() for ch in code)


def _fetch_us_daily(code: str, days: int) -> list[dict]:
    """yfinance 日K → 映射成 FinMind 同 schema(date/open/max/min/close/Trading_Volume)。"""
    try:
        import yfinance as yf
        start = (date.today() - timedelta(days=days + 10)).isoformat()
        df = yf.Ticker(code).history(start=start)  # 預設 auto_adjust=True
        if df is None or df.empty:
            return []
        rows: list[dict] = []
        for ts, r in df.iterrows():
            close = float(r["Close"])
            if close != close:  # NaN(當日盤中未完成 bar 的佔位列)→ 丟掉
                continue
            rows.append({
                "date": ts.date().isoformat(),
                "open": float(r["Open"]), "max": float(r["High"]),
                "min": float(r["Low"]), "close": close,
                "Trading_Volume": float(r.get("Volume", 0) or 0),
            })
        return rows
    except Exception as exc:
        logger.warning("yfinance daily %s failed: %s", code, exc)
        return []


def _fetch_daily(code: str, days: int = 180) -> list[dict]:
    if _is_us(code):
        return _fetch_us_daily(code.upper(), days)
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockPrice", "data_id": code,
                    "start_date": start, "token": _TOKEN},
            timeout=15,
        )
        rows = r.json().get("data", [])
        return [x for x in rows if x.get("close")]
    except Exception as exc:
        logger.warning("fetch %s failed: %s", code, exc)
        return []


def _ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    k = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _sma(values: list[float], window: int) -> list[float]:
    """簡單移動平均，前段不足以 None 補齊。"""
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - window:i + 1]) / window)
    return out


def _analyze(code: str, name: str) -> dict:
    rows = _fetch_daily(code)
    if len(rows) < 70:
        return {"code": code, "name": name, "ok": False, "msg": "資料不足"}

    closes = [float(r["close"]) for r in rows]
    last = closes[-1]

    # ── 1. 均線多頭排列 ──────────────────────────────────────────
    ma5  = _sma(closes, 5)[-1]
    ma10 = _sma(closes, 10)[-1]
    ma20 = _sma(closes, 20)[-1]
    ma60 = _sma(closes, 60)[-1]
    bull_stack = (ma5 > ma10 > ma20 > ma60) and (last >= ma5)
    # 部分多頭：至少短中期向上
    partial = (ma5 > ma20) and (last >= ma20)

    # ── 2. MACD ─────────────────────────────────────────────────
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    macd = _ema(dif, 9)            # 慢線(signal)
    hist = [d - m for d, m in zip(dif, macd)]
    # 黃金交叉：昨日柱<=0 今日柱>0；或柱由負轉正擴大
    macd_cross = len(hist) >= 2 and hist[-2] <= 0 < hist[-1]
    macd_pos   = hist[-1] > 0 and dif[-1] > 0   # 柱在零軸上方且 DIF>0

    # ── 3. 乖離率黃金交叉 ────────────────────────────────────────
    ma_s = _sma(closes, BIAS_SHORT)
    bias = [(c - m) / m * 100 if m else None for c, m in zip(closes, ma_s)]
    bias_clean = [b for b in bias if b is not None]
    bias_short_avg = _sma(bias_clean, BIAS_SHORT)   # 短期乖離率平均線
    bias_long_avg  = _sma(bias_clean, BIAS_LONG)    # 長期乖離率平均線
    bias_cross = False
    if len(bias_short_avg) >= 2 and bias_short_avg[-1] is not None and bias_long_avg[-1] is not None:
        prev_s, prev_l = bias_short_avg[-2], bias_long_avg[-2]
        if prev_s is not None and prev_l is not None:
            bias_cross = (prev_s <= prev_l) and (bias_short_avg[-1] > bias_long_avg[-1])
    bias_today = bias_clean[-1] if bias_clean else 0.0
    bias_ok = (bias_short_avg[-1] is not None and bias_long_avg[-1] is not None
               and bias_short_avg[-1] > bias_long_avg[-1] and bias_today > 0)

    # ── 綜合分數 ─────────────────────────────────────────────────
    score = sum([bull_stack, macd_pos, bias_ok])

    return {
        "code": code, "name": name, "ok": True, "last": last,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "bull_stack": bull_stack, "partial": partial,
        "dif": dif[-1], "macd": macd[-1], "hist": hist[-1],
        "macd_cross": macd_cross, "macd_pos": macd_pos,
        "bias_today": bias_today,
        "bias_short_avg": bias_short_avg[-1], "bias_long_avg": bias_long_avg[-1],
        "bias_cross": bias_cross, "bias_ok": bias_ok,
        "score": score,
    }


def _fmt(res: dict) -> str:
    if not res["ok"]:
        return f"📌 {res['code']} {res['name']}：{res['msg']}"

    def yn(b: bool) -> str:
        return "✅" if b else "❌"

    cross_tag = "🔥剛黃金交叉" if res["macd_cross"] else ""
    bias_cross_tag = "🔥剛黃金交叉" if res["bias_cross"] else ""
    stars = "★" * res["score"] + "☆" * (3 - res["score"])

    return (
        f"📌 {res['code']} {res['name']}  收={res['last']:.1f}  第三刀 {stars} ({res['score']}/3)\n"
        f"  ① 均線多頭排列 {yn(res['bull_stack'])}"
        f"  MA5={res['ma5']:.1f} 10={res['ma10']:.1f} 20={res['ma20']:.1f} 60={res['ma60']:.1f}"
        f"{'' if res['bull_stack'] else ('（部分多頭）' if res['partial'] else '（均線糾結/空頭）')}\n"
        f"  ② MACD {yn(res['macd_pos'])} {cross_tag}"
        f"  DIF={res['dif']:.1f} MACD={res['macd']:.1f} 柱={res['hist']:+.1f}\n"
        f"  ③ 乖離率黃金交叉 {yn(res['bias_ok'])} {bias_cross_tag}"
        f"  今日BIAS={res['bias_today']:+.1f}%"
        f"  短均={res['bias_short_avg']:+.1f} 長均={res['bias_long_avg']:+.1f}"
    )


def run(tickers: dict[str, str]) -> str:
    lines = ["🗡️ 鑽豹第三刀 — 技術面三指標檢核\n"]
    results = []
    for code, name in tickers.items():
        res = _analyze(code, name)
        results.append(res)
    # 依分數排序
    results.sort(key=lambda r: r.get("score", -1), reverse=True)
    for res in results:
        lines.append(_fmt(res))
        lines.append("")

    # 摘要
    qualified = [r for r in results if r.get("score", 0) >= 2]
    lines.append("━━ 摘要 ━━")
    if qualified:
        lines.append("第三刀 2/3 以上（技術面轉強）:")
        for r in qualified:
            lines.append(f"  {r['code']} {r['name']} ({r['score']}/3)")
    else:
        lines.append("目前無標的滿足第三刀 2/3 條件")
    lines.append("\n⚠️ 第三刀為「加碼確認」訊號，需配合第一刀(賺賠比)、第二刀(基本面)使用")
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("codes", nargs="*", help="股票代號（留空用預設清單）")
    parser.add_argument("--tg", action="store_true", help="推送 Telegram")
    args = parser.parse_args()

    if args.codes:
        tickers = {c: DEFAULT_TICKERS.get(c, c) for c in args.codes}
    else:
        tickers = DEFAULT_TICKERS

    report = run(tickers)
    print(report)

    if args.tg:
        import asyncio
        from backend.daily_signal import _send_telegram
        asyncio.run(_send_telegram(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
