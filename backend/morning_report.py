"""早盤報告（鑽豹 Top-Down）— 每天 07:00 自動推 Telegram。

抓取來源（全部公開 API，不需額外付費）：
  TWSE  — 三大法人現貨買賣超
  TAIFEX — 台指期三大法人未平倉口數
  FinMind — 個股近期價格 + 籌碼
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
logger = logging.getLogger("morning_report")

_FINMIND_TOKEN = (os.getenv("FINMIND_TOKEN") or os.getenv("FINMIND_API_TOKEN") or "")


# ── 最近交易日 ────────────────────────────────────────────────────────────────

def _last_trading_date() -> tuple[str, dict]:
    """回傳 (YYYYMMDD, twse_json)。"""
    for d in range(0, 7):
        chk = (date.today() - timedelta(days=d)).strftime("%Y%m%d")
        try:
            r = requests.get(
                "https://www.twse.com.tw/rwd/zh/fund/T86",
                params={"response": "json", "selectType": "ALL", "date": chk},
                timeout=10,
            )
            js = r.json()
            if js.get("stat") == "OK" and js.get("data"):
                return chk, js
        except Exception:
            pass
    return "", {}


# ── TWSE 三大法人現貨 ─────────────────────────────────────────────────────────

def _twse_chip(twse_json: dict) -> dict:
    rows = twse_json.get("data", [])
    # 合計行 = 代號欄非純數字
    totals = [r for r in rows if not r[0].replace(",", "").strip().isdigit()]
    mkt = totals[-1] if totals else rows[-1]

    def _n(s):
        try:
            return int(s.replace(",", "").replace("+", ""))
        except Exception:
            return 0

    tsmc = next((r for r in rows if r[0] == "2330"), None)
    return {
        "foreign": _n(mkt[4]),
        "trust": _n(mkt[10]),
        "dealer": _n(mkt[11]),
        "total": _n(mkt[-1]),
        "tsmc_foreign": _n(tsmc[4]) if tsmc else 0,
        "tsmc_total": _n(tsmc[-1]) if tsmc else 0,
    }


# ── TAIFEX 期貨未平倉 ─────────────────────────────────────────────────────────

def _taifex_oi(tai_date: str, product: str = "TXF") -> dict:
    try:
        r = requests.get(
            "https://www.taifex.com.tw/cht/3/futContractsDate",
            params={"queryDate": tai_date, "commodityId": product},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        soup = BeautifulSoup(r.text, "lxml")
        tbl = soup.find("table", class_="table_f")
        out = {}
        if not tbl:
            return out
        for row in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells and cells[0] in ("自營商", "投信", "外資") and len(cells) >= 12:
                def _i(s):
                    try:
                        return int(s.replace(",", "").replace("+", ""))
                    except Exception:
                        return 0
                out[cells[0]] = {
                    "long": _i(cells[7]),
                    "short": _i(cells[9]),
                    "net": _i(cells[11]),
                }
        return out
    except Exception as exc:
        logger.warning("taifex fetch failed: %s", exc)
        return {}


# ── FinMind 個股資料 ──────────────────────────────────────────────────────────

def _fm_price(code: str, start: str = "2026-04-01") -> list:
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockPrice", "data_id": code,
                    "start_date": start, "token": _FINMIND_TOKEN},
            timeout=10,
        )
        return r.json().get("data", [])
    except Exception:
        return []


def _fm_chip_5d(code: str) -> tuple[int, int]:
    """回傳 (外資5日淨買超股數, 投信5日淨買超股數)。"""
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInstitutionalInvestorsBuySell",
                    "data_id": code, "start_date": (date.today() - timedelta(days=14)).isoformat(),
                    "token": _FINMIND_TOKEN},
            timeout=10,
        )
        rows = r.json().get("data", [])
        by_date: dict[str, dict] = {}
        for row in rows:
            d = row["date"]
            if d not in by_date:
                by_date[d] = {}
            by_date[d][row["name"]] = row["buy"] - row["sell"]
        dates = sorted(by_date)[-5:]
        fgn   = sum(by_date[d].get("Foreign_Investor", 0) for d in dates)
        trust = sum(by_date[d].get("Investment_Trust", 0) for d in dates)
        return fgn, trust
    except Exception:
        return 0, 0


# ── 漲幅 >=5% 大量股清單 ──────────────────────────────────────────────────────

def _big_movers(date_str: str, min_pct: float = 5.0, min_lots: int = 1000) -> list:
    try:
        r = requests.get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL",
            params={"response": "json", "date": date_str},
            timeout=15,
        )
        rows = r.json().get("data", [])
    except Exception:
        return []

    results = []
    for row in rows:
        try:
            if len(row) < 9:
                continue
            code = row[0].strip()
            if not (code.isdigit() and len(code) == 4):
                continue
            close  = float(row[7].replace(",", ""))
            diff_s = row[8].replace(",", "").strip()
            if not diff_s or diff_s in ("--", "X0.00"):
                continue
            diff = float(diff_s)
            prev = close - diff
            if prev <= 0:
                continue
            pct  = diff / prev * 100
            lots = int(row[2].replace(",", "")) // 1000
            if pct >= min_pct and lots >= min_lots:
                results.append({"code": code, "name": row[1], "pct": round(pct, 1),
                                 "close": close, "diff": diff, "lots": lots})
        except Exception:
            pass
    return sorted(results, key=lambda x: x["pct"], reverse=True)


# ── 報告生成 ──────────────────────────────────────────────────────────────────

def generate() -> str:
    date_str, twse_json = _last_trading_date()
    if not date_str:
        return "❌ 無法取得最近交易日資料"

    tai_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
    readable  = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"

    chip   = _twse_chip(twse_json)
    txf_oi = _taifex_oi(tai_date, "TXF")
    movers = _big_movers(date_str)[:10]

    # 台積電近期收盤
    tsmc_prices = _fm_price("2330", start=(date.today() - timedelta(days=14)).isoformat())
    tsmc_last = tsmc_prices[-1] if tsmc_prices else {}

    def _m(n: int) -> str:
        if abs(n) >= 1_000_000:
            return f"{n/1_000_000:+.1f}M股"
        if abs(n) >= 1_000:
            return f"{n/1_000:+.0f}K股"
        return f"{n:+d}股"

    lines = [f"📊 鑽豹盤前報告  {readable}\n"]

    # ── 一、籌碼照妖鏡 ───────────────────────────────────────────────────────
    lines.append("━━ 一、籌碼照妖鏡 ━━")
    lines.append(f"現貨三大 | 外資 {_m(chip['foreign'])}  投信 {_m(chip['trust'])}  自營 {_m(chip['dealer'])}")
    lines.append(f"三大合計 | {_m(chip['total'])}")
    tsmc_close  = tsmc_last.get("close", "?")
    tsmc_spread = tsmc_last.get("spread", 0)
    lines.append(f"台積電   | 外資 {_m(chip['tsmc_foreign'])}  收={tsmc_close}  漲跌={tsmc_spread:+.0f}" if isinstance(tsmc_spread, (int, float)) else f"台積電   | 外資 {_m(chip['tsmc_foreign'])}  收={tsmc_close}")

    # 期貨
    if "外資" in txf_oi:
        fgn = txf_oi["外資"]
        trust = txf_oi.get("投信", {})
        ratio = fgn["long"] / fgn["short"] if fgn.get("short") else 0
        lines.append(f"\nTXF未平倉")
        lines.append(f"  外資 多{fgn['long']:,} 空{fgn['short']:,} 淨{fgn['net']:+,}口")
        if trust:
            lines.append(f"  投信 多{trust['long']:,} 空{trust['short']:,} 淨{trust['net']:+,}口")
        if fgn["net"] < -30000:
            lines.append(f"  ⚠️ 外資期貨巨空（多/空={ratio:.2f}），軋空燃料充足")
        elif fgn["net"] > 30000:
            lines.append(f"  ✅ 外資期貨淨多，偏多方向")

    # ── 二、今日強勢題材 ──────────────────────────────────────────────────────
    lines.append("\n━━ 二、強勢題材（漲≥5%+量≥千張）━━")
    if movers:
        for m in movers[:8]:
            lines.append(f"  {m['code']} {m['name']:6s} +{m['pct']:.1f}% {m['lots']:,}張")
    else:
        lines.append("  （無符合條件標的）")

    # ── 三、鑽豹第一刀候選（取前2大量股做籌碼追蹤）────────────────────────
    lines.append("\n━━ 三、鑽豹第一刀候選 ━━")
    candidates = [m for m in movers if m["lots"] >= 5000][:2]
    if not candidates:
        candidates = movers[:2]

    for m in candidates:
        prices = _fm_price(m["code"])
        fgn5, trust5 = _fm_chip_5d(m["code"])
        if prices:
            min_close = min(p["close"] for p in prices)
            from_low = (m["close"] - min_close) / min_close * 100 if min_close else 0
            prev = m["close"] - m["diff"]
            stop_pct = 10.0
            stop_loss = round(m["close"] * (1 - stop_pct / 100), 1)
            rr = "⚠️ 無法估算"
            note = ""
            if from_low < 30:
                target_pct = 20
                rr = f"賺賠比 ≈ {target_pct/stop_pct:.1f}x ✅"
                note = "距低點近，第一刀條件較佳"
            elif from_low < 60:
                rr = "賺賠比偏低，等回檔再觀察"
                note = "中段，追高風險增加"
            else:
                rr = "高位追漲，不符第一刀"
                note = "已大漲，跳過"

            lines.append(
                f"\n📌 {m['code']} {m['name']}\n"
                f"  收={m['close']}  +{m['pct']:.1f}%  量={m['lots']:,}張\n"
                f"  外資5日: {fgn5//1000:+,}K股  投信5日: {trust5//1000:+,}K股\n"
                f"  距4月低: +{from_low:.0f}%  {note}\n"
                f"  停損:{stop_loss}  {rr}"
            )
        else:
            lines.append(f"\n📌 {m['code']} {m['name']}  +{m['pct']:.1f}%  （FinMind資料不足）")

    # ── 四、鑽豹第三刀掃描（追蹤清單 + 今日大漲股）────────────────────────
    lines.append("\n━━ 四、鑽豹第三刀掃描 ━━")
    lines.append(_blade3_section(movers))

    # ── 五、合約負債監控（雷老闆指標五，僅掃固定追蹤清單）──────────────────
    lines.append("\n━━ 五、合約負債監控（領先指標）━━")
    lines.append(_contract_section())

    lines.append("\n⚠️ 此報告為輔助決策參考，不構成投資建議")
    return "\n".join(lines)


# ── 合約負債監控（接 contract_liab）──────────────────────────────────────────

def _contract_section() -> str:
    """掃固定追蹤清單的合約負債趨勢，重點標示『由升轉降』出場警示。"""
    try:
        from backend.contract_liab import analyze, DEFAULT_TICKERS
    except Exception as exc:
        return f"  （合約負債模組載入失敗：{exc}）"

    rising, exiting, na = [], [], []
    for code, name in DEFAULT_TICKERS.items():
        try:
            r = analyze(code, name)
        except Exception:
            continue
        if not r.get("ok"):
            na.append(f"{code}{name}")
            continue
        sig = r.get("signal", "")
        cl_e = r["cl_last"] / 1e8
        gate = "達標" if r["passed"] else "未達門檻"
        if "由升轉降" in sig:
            exiting.append(f"  ⚠️ {code} {name} {cl_e:.0f}億 {r['trend']}（億）由升轉降→減碼")
        elif "連升" in sig:
            rising.append(f"  📈 {code} {name} {cl_e:.0f}億 {r['trend']}（億）連升・{gate}")

    out = []
    if exiting:
        out.append("出場警示:")
        out.extend(exiting)
    if rising:
        out.append("接單轉強（合約負債連升）:")
        out.extend(rising)
    if not out:
        out.append("  （追蹤清單無明顯合約負債訊號）")
    if na:
        out.append(f"  不適用此指標: {'、'.join(na)}")
    return "\n".join(out)


# ── 第三刀掃描（接 diamond_blade3）────────────────────────────────────────────

def _blade3_section(movers: list) -> str:
    """掃描追蹤清單 + 今日大漲股，列出剛發動或滿足第三刀的標的。"""
    try:
        from backend.diamond_blade3 import _analyze, DEFAULT_TICKERS
    except Exception as exc:
        return f"  （第三刀模組載入失敗：{exc}）"

    # 掃描對象：固定追蹤清單 + 今日大漲前 6 名（去重）
    watch: dict[str, str] = dict(DEFAULT_TICKERS)
    for m in movers[:6]:
        watch.setdefault(m["code"], m["name"])

    fired, qualified = [], []
    for code, name in watch.items():
        try:
            r = _analyze(code, name)
        except Exception:
            continue
        if not r.get("ok"):
            continue
        if r.get("macd_cross") or r.get("bias_cross"):
            fired.append(r)
        elif r.get("score", 0) >= 2:
            qualified.append(r)

    out = []
    if fired:
        out.append("🔥 今日剛發動（MACD/乖離率剛黃金交叉）:")
        for r in sorted(fired, key=lambda x: x["score"], reverse=True):
            tag = []
            if r.get("macd_cross"):
                tag.append("MACD金叉")
            if r.get("bias_cross"):
                tag.append("乖離金叉")
            out.append(f"  {r['code']} {r['name']} 收={r['last']:.1f} ({r['score']}/3) [{'+'.join(tag)}]")
    if qualified:
        out.append("✅ 技術面已轉強（第三刀 2/3 以上）:")
        for r in sorted(qualified, key=lambda x: x["score"], reverse=True):
            out.append(f"  {r['code']} {r['name']} 收={r['last']:.1f} ({r['score']}/3)")
    if not out:
        out.append("  （追蹤清單與今日強勢股均未觸發第三刀訊號）")
    return "\n".join(out)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--tg", action="store_true", help="Send to Telegram")
    args = parser.parse_args()

    report = generate()
    print(report)

    if args.tg:
        import asyncio
        from backend.daily_signal import _send_telegram
        asyncio.run(_send_telegram(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
