"""
Assembles Telegram messages and handles signal file persistence.

Message layout (returns list[str], each ≤ 4000 chars):
  Part 1: header + 積極佈局 (full detail rows)
  Part 2: 觀察等待 (top 10) + 謹慎觀察 (top 5) + 注意事項

Parse mode: HTML
"""
import json
import numpy as np
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from loguru import logger
from strategy.signal import Signal
from config.settings import settings

_WEEKDAY_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

REC_EMOJI = {
    "積極佈局": "🟢",
    "觀察等待": "🟡",
    "謹慎觀察": "🔵",
    "排除":     "🔴",
}

MA_SLOPE_LABEL  = {"up": "↑上揚", "flat": "→平緩", "down": "↓下降", "unknown": "?"}
STATE_LABEL = {
    "long_bull":    "長線多頭",
    "turning_bull": "轉折向上",
    "bear":         "空頭趨勢",
    "unknown":      "資料不足",
}


# ── JSON serialization ────────────────────────────────────────────────────────

def _json_serializer(obj):
    if isinstance(obj, np.bool_):    return bool(obj)
    if isinstance(obj, np.integer):  return int(obj)
    if isinstance(obj, np.floating): return float(obj)
    if isinstance(obj, np.ndarray):  return obj.tolist()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


# ── Signal persistence ────────────────────────────────────────────────────────

def save_signals(signals: list[Signal], data_date: str) -> Path:
    """Serialize signals to data/signals_{data_date}.json. Returns the path."""
    report = {
        "report_date":  date.today().isoformat(),
        "data_date":    data_date,
        "saved_at":     datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total":        len(signals),
        "passed":       sum(1 for s in signals if s.hard_pass),
        "excluded":     sum(1 for s in signals if not s.hard_pass),
        "by_recommendation": {
            rec: sum(1 for s in signals if s.recommendation == rec)
            for rec in ("積極佈局", "觀察等待", "謹慎觀察", "排除")
        },
        "signals": [asdict(s) for s in signals],
    }
    path = Path(settings.data_dir) / f"signals_{data_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_serializer), encoding="utf-8")
    logger.info(f"[report] Signals saved → {path}")
    return path


def load_signals(data_date: str) -> list[Signal]:
    """Load Signal objects from data/signals_{data_date}.json."""
    path = Path(settings.data_dir) / f"signals_{data_date}.json"
    if not path.exists():
        logger.warning(f"[report] Signal file not found: {path}")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Signal(**s) for s in data["signals"]]
    except Exception as exc:
        logger.error(f"[report] Failed to load signals from {path}: {exc}")
        return []


# ── Row formatters ────────────────────────────────────────────────────────────

def _ma_status(trend: dict) -> str:
    slope = MA_SLOPE_LABEL.get(trend["ma240_slope"], "?")
    above = "✅" if trend["price_above_ma240"] else "❌"
    return f"{above}{slope}"


def _chip_status(chip: dict) -> str:
    c = chip["foreign_consecutive_buy_days"]
    if c >= 6:   return f"外資連買{c}天🔥"
    if c >= 3:   return f"外資連買{c}天✅"
    if c > 0:    return f"外資買{c}天"
    if c < 0:    return f"外資連賣{abs(c)}天⚠️"
    if chip["has_inst_buy_last5d"]: return "投信近期買超"
    return "無明顯法人買"


def _row(s: Signal) -> str:
    """Full detail row for 積極佈局."""
    ma   = _ma_status(s.A_trend)
    chip = _chip_status(s.B1_chip)
    return (
        f"<code>{s.symbol}</code> {s.name}\n"
        f"  {ma} | {chip} | {s.abc_score}/10"
    )


def _row_brief(s: Signal) -> str:
    """One-line compact row for 觀察等待/謹慎觀察."""
    return f"<code>{s.symbol}</code> {s.name} {s.abc_score}分"


# ── Message builders ──────────────────────────────────────────────────────────

def _get_data_date(signals: list[Signal]) -> str:
    if not signals:
        return date.today().isoformat()
    # generated_at is "YYYY-MM-DDTHH:MM:SS" — strip time part
    return signals[0].generated_at[:10]


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split a long message at newline boundaries to stay under limit."""
    if len(text) <= limit:
        return [text]
    parts, chunk = [], []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > limit:
            parts.append("\n".join(chunk))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        parts.append("\n".join(chunk))
    return parts


def build_telegram_messages(signals: list[Signal]) -> list[str]:
    """
    Returns list of Telegram-ready HTML strings (each ≤ 4000 chars).
    Part 1: header + 積極佈局
    Part 2: 觀察等待 + 謹慎觀察 + 注意事項
    """
    data_date   = _get_data_date(signals)
    weekday_zh  = _WEEKDAY_ZH[date.fromisoformat(data_date).weekday()]
    generated   = signals[0].generated_at if signals else "—"

    buy     = sorted([s for s in signals if s.recommendation == "積極佈局"], key=lambda x: -x.abc_score)
    watch   = sorted([s for s in signals if s.recommendation == "觀察等待"], key=lambda x: -x.abc_score)
    caution = sorted([s for s in signals if s.recommendation == "謹慎觀察"], key=lambda x: -x.abc_score)
    passed  = len(buy) + len(watch) + len(caution)
    excluded = len(signals) - passed

    # ── Part 1: header + 積極佈局 ──
    p1 = [
        "📊 <b>台股 ABC 選股日報</b>",
        f"資料日期 {data_date}（{weekday_zh}）",
        f"掃描 {len(signals):,} 檔 | 通過 <b>{passed}</b> 檔（積極 {len(buy)} | 觀察 {len(watch)} | 謹慎 {len(caution)}）",
        "",
        f"<b>━━ 🟢 積極佈局（{len(buy)} 檔）━━</b>",
    ]
    if buy:
        for s in buy:
            p1.append(_row(s))
    else:
        p1.append("今日無符合標的")

    # ── Part 2: 觀察等待 + 謹慎觀察 + 注意事項 ──
    p2 = []

    if watch:
        top_n = min(10, len(watch))
        p2.append(f"<b>━━ 🟡 觀察等待（{len(watch)} 檔，顯示前 {top_n}）━━</b>")
        for s in watch[:top_n]:
            p2.append(_row_brief(s))
        if len(watch) > top_n:
            p2.append(f"...及其他 {len(watch) - top_n} 檔")

    if caution:
        top_n = min(5, len(caution))
        p2.append(f"\n<b>━━ 🔵 謹慎觀察（{len(caution)} 檔，顯示前 {top_n}）━━</b>")
        for s in caution[:top_n]:
            p2.append(_row_brief(s))
        if len(caution) > top_n:
            p2.append(f"...及其他 {len(caution) - top_n} 檔")

    # 注意事項
    notes = []
    if signals and signals[0].B1_chip.get("friday_patch_needed"):
        notes.append("⚠️ 週末籌碼黑洞：週五法人數據請手動確認")
    if excluded:
        notes.append(f"🔴 排除 {excluded:,} 檔（未達硬性條件 H1–H4）")

    if notes:
        p2.append("\n<b>━━ 📝 注意事項 ━━</b>")
        p2 += notes

    p2.append(f"\n<i>分析完成 {generated}</i>")

    # Assemble and split to stay under Telegram's 4096 char limit
    messages = []
    for part_lines in [p1, p2]:
        if not part_lines:
            continue
        for chunk in _split_message("\n".join(part_lines)):
            messages.append(chunk)

    return messages


def build_detail_message(signal: Signal) -> str:
    """Per-stock deep-dive card for 積極佈局 stocks."""
    e  = REC_EMOJI.get(signal.recommendation, "⚪")
    t  = signal.A_trend
    c  = signal.B1_chip
    w  = signal.washout
    ma20 = MA_SLOPE_LABEL.get(t["ma20_slope"], "?")
    ma60 = MA_SLOPE_LABEL.get(t["ma60_slope"], "?")
    above = "✅" if t["price_above_ma240"] else "❌"

    return (
        f"{e} <b>{signal.symbol} {signal.name}</b>  評分 {signal.abc_score}/10\n"
        f"年線: {MA_SLOPE_LABEL.get(t['ma240_slope'],'?')} MA={t['ma240_value']} | 現價={t['current_price']} {above}\n"
        f"月線: {ma20} | 季線: {ma60}\n"
        f"外資連買: {c['foreign_consecutive_buy_days']}天 | 近5日淨:{c['net_foreign_5d']}張\n"
        f"投信近5日: {c['net_trust_5d']}張 | 融資: {c['margin_trend']}\n"
        f"洗盤: {'是' if w['detected'] else '否'} — {w['description']}\n\n"
        f"<i>{signal.story}</i>"
    )


# ── Live per-stock card ───────────────────────────────────────────────────────

def build_live_card(signal: Signal) -> str:
    """
    Live push card (sent per-stock during scheduled analysis).
    Uses same header format as bot query cards for consistency.
    """
    _SLOPE = {"up": "↑", "flat": "→", "down": "↓", "unknown": "?"}
    _STATE_ZH = {
        "long_bull":    "長線多頭",
        "turning_bull": "轉折向上⭐",
        "bear":         "空頭趨勢",
        "unknown":      "資料不足",
    }
    e   = REC_EMOJI.get(signal.recommendation, "⚪")
    t   = signal.A_trend
    c   = signal.B1_chip
    w   = signal.washout

    above    = "✅年線上" if t["price_above_ma240"] else "❌年線下"
    state_zh = _STATE_ZH.get(t["state"], "?")
    slope    = _SLOPE.get(t["ma240_slope"], "?")
    chip_str = _chip_status(c)
    ma60     = _SLOPE.get(t["ma60_slope"], "?")

    tags = []
    if w["b2_breakout"]:               tags.append("B2突破🚀")
    if w["detected"]:                  tags.append("洗盤中🧹")
    if w["accumulation_on_decline"]:   tags.append("量縮吸籌📦")
    if t["deduction_drop_imminent"]:   tags.append("扣抵將降📉")
    if c["margin_confluence"]:         tags.append("融資合流🤝")
    if c["contrarian_on_weak_market"]: tags.append("逆勢🔥")

    line1 = f"{e} <b>{signal.symbol} {signal.name}</b>  分數:{signal.abc_score}/10"
    line2 = f"{above} {state_zh}{slope} | {chip_str}"
    line3 = f"MA60{ma60}" + (f"  {'  '.join(tags)}" if tags else "")
    line4 = f"<code>{signal.recommendation}</code>"
    return "\n".join([line1, line2, line3, line4])


# ── Alert / system message builders ──────────────────────────────────────────

def build_error_alert(job_name: str, error: str) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"🚨 <b>排程任務失敗通知</b>\n"
        f"任務：<code>{job_name}</code>\n"
        f"時間：{now}\n"
        f"錯誤：<code>{error[:300]}</code>"
    )


def build_heartbeat_warning(detail: str) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"⏰ <b>07:55 資料就緒警告</b>\n"
        f"時間：{now}\n"
        f"{detail}\n\n"
        f"請確認排程是否正常執行。"
    )


def build_no_trading_day_notice() -> str:
    today = date.today()
    weekday_zh = _WEEKDAY_ZH[today.weekday()]
    return f"📅 今日（{today.isoformat()} {weekday_zh}）非交易日，跳過選股排程。"


# ── Weekend report builders ───────────────────────────────────────────────────

def build_saturday_volume_message(stocks: list[dict], trading_date: str) -> str:
    """
    Saturday report: top 10 by trading volume.
    stocks: [{"symbol", "name", "volume"(張), "close", "market"}, ...]
    """
    weekday_zh = _WEEKDAY_ZH[date.fromisoformat(trading_date).weekday()]
    lines = [
        "📊 <b>本週成交量 Top 10</b>",
        f"資料日期 {trading_date}（{weekday_zh}）| 上市＋上櫃全市場",
        "",
        "<b>#   代號    名稱        成交量(張)    收盤價</b>",
        "─" * 38,
    ]
    for i, s in enumerate(stocks, 1):
        market_tag = "🏦" if s.get("market") == "twse" else "🏪"
        vol_str = f"{s['volume']:>10,}"
        close_str = f"{s['close']:>7.1f}"
        lines.append(
            f"{i:2d}. {market_tag}<code>{s['symbol']}</code> "
            f"{s['name'][:6]:<6}  {vol_str}  {close_str}"
        )
    lines.append(f"\n🏦=上市  🏪=上櫃  成交量單位：張（千股）")
    lines.append(f"<i>發送時間 {datetime.now().strftime('%H:%M:%S')}</i>")
    return "\n".join(lines)


def build_sunday_foreign_message(stocks: list[dict], trading_date: str) -> str:
    """
    Sunday report: top 10 by foreign investor net buy.
    stocks: [{"symbol", "name", "foreign_net"(千股), "market"}, ...]
    """
    weekday_zh = _WEEKDAY_ZH[date.fromisoformat(trading_date).weekday()]
    lines = [
        "🌏 <b>本週外資買超 Top 10</b>",
        f"資料日期 {trading_date}（{weekday_zh}）| 上市＋上櫃全市場",
        "",
        "<b>#   代號    名稱        外資買超(千股)</b>",
        "─" * 35,
    ]
    for i, s in enumerate(stocks, 1):
        market_tag = "🏦" if s.get("market") == "twse" else "🏪"
        net = s["foreign_net"]
        sign = "+" if net >= 0 else ""
        lines.append(
            f"{i:2d}. {market_tag}<code>{s['symbol']}</code> "
            f"{s['name'][:6]:<6}  {sign}{net:,}"
        )
    lines.append(f"\n🏦=上市  🏪=上櫃  單位：千股")
    lines.append(f"<i>發送時間 {datetime.now().strftime('%H:%M:%S')}</i>")
    return "\n".join(lines)


# ── 量縮回測摘要報告 ───────────────────────────────────────────────────────────

def build_backtest_message(summary: dict, run_date: str, csv_path: str) -> list[str]:
    """
    量縮不破低回測摘要 Telegram 訊息。
    summary: compute_summary() 回傳的 dict。
    回傳 list[str]，每段 ≤ 4000 字元（HTML 格式）。
    """
    weekday_zh = _WEEKDAY_ZH[date.fromisoformat(run_date).weekday()]

    def _fmt_ret(avg, wr):
        if avg is None:
            return "N/A"
        sign = "+" if avg >= 0 else ""
        return f"{sign}{avg:.1f}%（勝率{wr:.0f}%）"

    total  = summary["total_patterns"]
    pass_a = summary["pass_a"]
    pab1   = summary["pass_ab1"]
    passed = summary["passed"]

    lines = [
        "📊 <b>連續五日量縮不破低 回測報告</b>",
        f"回測期間：過去 2 年  |  日期 {run_date}（{weekday_zh}）",
        "",
        "<b>━━ 篩選漏斗 ━━</b>",
        f"型態命中（原始）：<b>{total:,}</b> 次",
        f"通過 A（長多結構）：<b>{pass_a}</b>  "
        f"（{pass_a/total*100:.0f}%）" if total else "",
        f"通過 A+B1（吸籌特徵）：<b>{pab1}</b>  "
        f"（{pab1/total*100:.0f}%）" if total else "",
        f"通過 A+B1+B2（賣壓消失）：<b>{passed}</b>  "
        f"（{passed/total*100:.0f}%）" if total else "",
        "",
    ]

    if passed == 0:
        lines.append("⚠️ 無符合 A+B1+B2 的歷史結果，無法計算勝率。")
    else:
        lines += [
            "<b>━━ 勝率統計（A+B1+B2 通過者）━━</b>",
            f"  5日後報酬：{_fmt_ret(summary['avg_r5'],  summary['wr5'])}",
            f" 10日後報酬：{_fmt_ret(summary['avg_r10'], summary['wr10'])}",
            f" 20日後報酬：{_fmt_ret(summary['avg_r20'], summary['wr20'])}",
            "",
        ]
        if summary["top_stocks"]:
            lines.append("<b>━━ 歷史觸發最多的標的 ━━</b>")
            for name_sym, cnt in summary["top_stocks"]:
                lines.append(f"  {name_sym}：{cnt} 次")

    lines += [
        "",
        f"📁 完整結果：<code>{csv_path}</code>",
        f"<i>回測完成 {datetime.now().strftime('%H:%M:%S')}</i>",
    ]

    messages = []
    for chunk in _split_message("\n".join(lines)):
        messages.append(chunk)
    return messages


# ── 量縮不破低報告 ─────────────────────────────────────────────────────────────

def build_shortage_radar_message(
    signals: list,
    scan_date: str,
    symbol_count: int,
    clusters: dict,
) -> list[str]:
    """
    缺貨雷達報告 Telegram 訊息。
    signals: list[ShortageSignal]（已排序）
    clusters: {sector: [symbols]} 同族群共振
    回傳 list[str]，每段 ≤ 4000 字元（HTML 格式）。
    """
    weekday_zh = _WEEKDAY_ZH[date.fromisoformat(scan_date).weekday()]
    hot = [s for s in signals if s.score >= 4]
    potential = [s for s in signals if s.score == 3]

    _GRADE_EMOJI = {
        "龍頭瀑布": "⚡",
        "強缺貨":   "🔴",
        "潛在缺貨": "🟠",
        "觀察中":   "🟡",
        "不符合":   "—",
    }
    _TIER_TAG = {
        "tier1": "【龍頭】",
        "tier2": "【二線】",
        "":      "",
    }

    def _trend_bar(yoy_vals: list) -> str:
        bars = []
        for v in yoy_vals:
            if v is None or (isinstance(v, float) and v != v):
                bars.append("?")
            elif v >= 30:
                bars.append("▲▲")
            elif v >= 10:
                bars.append("▲")
            elif v >= 0:
                bars.append("▬")
            else:
                bars.append("▼")
        return "→".join(bars)

    def _signal_row(s) -> str:
        emoji = _GRADE_EMOJI.get(s.grade, "—")
        tier_tag = _TIER_TAG.get(getattr(s, "tier", ""), "")
        acc = getattr(s, "acceleration", None)
        acc_str = (
            f"+{acc:.1f}%↑" if acc is not None and acc > 0
            else f"{acc:.1f}%↓" if acc is not None
            else ""
        )
        yoy_bar = _trend_bar(s.yoy_trend)
        sector_str = s.sectors[0] if s.sectors else ""
        cascade_tag = " 💧龍頭瀑布" if getattr(s, "cascade_bonus", False) else ""

        line1 = (
            f"{emoji} <code>{s.symbol}</code> {s.name}{tier_tag}{cascade_tag}\n"
            f"  YoY {s.latest_yoy:+.1f}% {acc_str} | {yoy_bar} | {sector_str}"
        )
        # Enrichment badges (Phase 2 financial data)
        enrichment = getattr(s, "enrichment", None)
        if enrichment and enrichment.badges:
            line1 += "\n  " + " | ".join(enrichment.badges[:4])
        return line1

    cascade_sigs = [s for s in signals if getattr(s, "cascade_bonus", False)]
    hot = [s for s in signals if s.score >= 4 and not getattr(s, "cascade_bonus", False)]
    potential = [s for s in signals if s.score == 3 and not getattr(s, "cascade_bonus", False)]

    lines = [
        "📡 <b>缺貨雷達掃描報告</b>",
        f"掃描日期 {scan_date}（{weekday_zh}）| 共掃描 {symbol_count} 檔",
        f"龍頭瀑布 ⚡{len(cascade_sigs)} | 強缺貨 🔴{len(hot)} | 潛在缺貨 🟠{len(potential)}",
        "",
    ]

    if cascade_sigs:
        lines.append(f"<b>━━ ⚡ 龍頭瀑布（二線受惠，{len(cascade_sigs)} 檔）━━</b>")
        lines.append("<i>龍頭產能滿載 → 訂單外溢二線 → 二線更飛</i>")
        for s in cascade_sigs:
            lines.append(_signal_row(s))
        lines.append("")

    if hot:
        lines.append(f"<b>━━ 🔴 強缺貨（{len(hot)} 檔）━━</b>")
        for s in hot:
            lines.append(_signal_row(s))
        lines.append("")

    if potential:
        top_n = min(8, len(potential))
        lines.append(f"<b>━━ 🟠 潛在缺貨（{len(potential)} 檔，前 {top_n}）━━</b>")
        for s in potential[:top_n]:
            lines.append(_signal_row(s))
        lines.append("")

    rotation_sigs = [s for s in signals if getattr(s, "rotation_candidate", False)]
    if rotation_sigs:
        lines.append(f"<b>━━ 🔄 時間差輪動補漲（{len(rotation_sigs)} 檔）━━</b>")
        lines.append("<i>族群領先股已漲多 → 轉進剛加速的落後股（東鋼→彰源）</i>")
        for s in rotation_sigs:
            leader = getattr(s, "rotation_leader", "")
            sector_str = s.sectors[0] if s.sectors else ""
            lines.append(
                f"🔄 <code>{s.symbol}</code> {s.name}（領先股 {leader}）\n"
                f"  YoY {s.latest_yoy:+.1f}% 剛轉強 | {sector_str}"
            )
        lines.append("")

    if clusters:
        lines.append("<b>━━ 🔗 供應鏈族群共振 ━━</b>")
        for sector, syms in clusters.items():
            lines.append(f"  {sector}：{'、'.join(syms)}")
        lines.append("")

    if not cascade_sigs and not hot and not potential and not rotation_sigs:
        lines.append("本次掃描無明顯缺貨訊號。")

    lines.append("<i>⚡龍頭瀑布 = 龍頭缺貨 → 訂單轉二線 → 二線股最具爆發力</i>")
    lines.append(f"<i>掃描完成 {datetime.now().strftime('%H:%M:%S')}</i>")

    messages = []
    for chunk in _split_message("\n".join(lines)):
        messages.append(chunk)
    return messages


def build_vol_shrink_message(matches: list, trading_date: str) -> list[str]:
    """
    連續五日量縮不破低 選股報告 Telegram 訊息。
    matches: list[VolShrinkMatch]（從 strategy.volume_shrink 匯入）
    回傳 list[str]，每段 ≤ 4000 字元（HTML 格式）。
    """
    weekday_zh = _WEEKDAY_ZH[date.fromisoformat(trading_date).weekday()]
    lines = [
        "📉 <b>連續五日量縮不破低 選股報告</b>",
        f"資料日期 {trading_date}（{weekday_zh}）",
        f"符合條件：<b>{len(matches)}</b> 檔",
        "",
    ]

    if not matches:
        lines.append("本日無符合標的")
    else:
        for m in matches:
            lines.append(f"<b>📌 {m.symbol}  {m.name}</b>")
            # 固定寬度標頭
            lines.append(
                "<code>"
                f"{'日期':<10} {'收盤':>6} {'成交量':>10} {'量縮':>6} {'最低':>7}"
                "</code>"
            )
            for d, c, v, pct, low in zip(
                m.dates, m.closes, m.volumes, m.vol_shrink_pcts, m.lows
            ):
                lines.append(
                    f"<code>"
                    f"{d}  {c:6.1f}  {v:>9,}  -{pct:.1f}%  {low:6.1f}"
                    f"</code>"
                )
            lines.append("")  # 每支股票後空一行

    lines.append(f"<i>掃描完成 {datetime.now().strftime('%H:%M:%S')}</i>")

    messages = []
    for chunk in _split_message("\n".join(lines)):
        messages.append(chunk)
    return messages
