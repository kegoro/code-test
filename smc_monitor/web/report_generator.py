# ============================================================
#  web/report_generator.py
#  HTML 分析報告生成器
# ============================================================

from datetime import datetime
from core.analyzer import ChartAnalysis


def _signal_badge(sig_type: str, direction: str) -> str:
    color_map = {
        "BOS":       ("#ff3355", "rgba(255,51,85,0.15)"),
        "CHoCH":     ("#ff6600", "rgba(255,102,0,0.15)"),
        "Weak Low":  ("#ffcc00", "rgba(255,204,0,0.15)"),
        "Weak High": ("#ffcc00", "rgba(255,204,0,0.15)"),
        "EQL":       ("#00aaff", "rgba(0,170,255,0.15)"),
        "FVG":       ("#ce93d8", "rgba(206,147,216,0.15)"),
        "OB":        ("#2eca7f", "rgba(46,202,127,0.15)"),
    }
    c, bg = color_map.get(sig_type, ("#ffffff", "rgba(255,255,255,0.1)"))
    arrow = " ↑" if direction == "bullish" else " ↓" if direction == "bearish" else ""
    return f'<span style="background:{bg};color:{c};border:1px solid {c}66;padding:3px 10px;border-radius:3px;font-size:11px;font-family:Space Mono,monospace;font-weight:700;letter-spacing:1px">{sig_type}{arrow}</span>'


def _price_color(val: float, ref: float = 0) -> str:
    if val < ref: return "#ff3355"
    if val > ref: return "#00ff88"
    return "#e8edf5"


def generate_html_report(analysis: ChartAnalysis, screenshot_url: str = "") -> str:
    """生成完整 HTML 分析報告"""

    now = datetime.now().strftime("%Y.%m.%d · %H:%M")
    struct_color = {
        "bullish": "#00ff88",
        "bearish": "#ff3355",
        "ranging": "#ffcc00",
        "neutral": "#4a5568",
    }.get(analysis.market_structure, "#4a5568")

    border_color = "#ff3355" if analysis.market_structure == "bearish" else "#00ff88"

    badges_html = " ".join(
        _signal_badge(s.type, s.direction) for s in analysis.signals
    )

    signals_rows = ""
    for s in analysis.signals:
        color = "#ff3355" if s.direction == "bearish" else "#00ff88" if s.direction == "bullish" else "#ffcc00"
        signals_rows += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1a2332">
            <div style="display:flex;align-items:center;gap:10px">
                <div style="width:6px;height:6px;border-radius:50%;background:{color}"></div>
                <span style="font-size:12px;color:#a0aec0">{s.type}</span>
            </div>
            <span style="font-family:Space Mono,monospace;font-size:13px;font-weight:700;color:{color}">
                {s.price_level:.2f}
            </span>
            <span style="font-size:11px;color:#4a5568;max-width:200px;text-align:right">{s.description}</span>
        </div>"""

    key_levels_rows = ""
    levels = []
    if analysis.premium_zone_top: levels.append(("Premium Zone 頂", analysis.premium_zone_top, "#ff3355", "供給"))
    if analysis.premium_zone_bot: levels.append(("Premium Zone 底", analysis.premium_zone_bot, "#ff6600", "阻力"))
    if analysis.equilibrium:      levels.append(("Equilibrium 均衡", analysis.equilibrium, "#ffcc00", "中性"))
    if analysis.discount_zone_top: levels.append(("Discount Zone 頂", analysis.discount_zone_top, "#00aaff", "支撐"))
    if analysis.discount_zone_bot: levels.append(("Discount Zone 底", analysis.discount_zone_bot, "#00ff88", "需求"))
    for wl in analysis.weak_lows:  levels.append(("Weak Low 脆弱低點", wl, "#ffcc00", "⚠ 流動性目標"))
    for wh in analysis.weak_highs: levels.append(("Weak High 脆弱高點", wh, "#ffcc00", "⚠ 流動性目標"))

    for name, price, color, status in levels:
        key_levels_rows += f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #0d1117">
            <div style="display:flex;align-items:center;gap:8px">
                <div style="width:6px;height:6px;border-radius:50%;background:{color}"></div>
                <span style="font-size:12px;color:#718096">{name}</span>
            </div>
            <span style="font-family:Space Mono,monospace;font-size:13px;font-weight:700;color:{color}">{price:.2f}</span>
            <span style="font-size:10px;padding:2px 7px;border-radius:2px;background:{color}1a;color:{color};font-family:Space Mono,monospace">{status}</span>
        </div>"""

    ob_rows = ""
    for ob in analysis.order_blocks:
        color = "#ff3355" if "bearish" in ob.get("type","") else "#00ff88"
        label = "空頭 OB" if "bearish" in ob.get("type","") else "多頭 OB"
        ob_rows += f"""
        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #0d1117">
            <span style="font-size:12px;color:#718096">{label}</span>
            <span style="font-family:Space Mono,monospace;font-size:12px;color:{color}">{ob.get('bot',0):.2f} – {ob.get('top',0):.2f}</span>
        </div>"""

    screenshot_section = ""
    if screenshot_url:
        screenshot_section = f"""
        <div style="background:#0d1117;border:1px solid #1a2332;border-radius:8px;padding:16px;margin-bottom:16px">
            <div style="font-size:10px;letter-spacing:2px;color:#4a5568;margin-bottom:10px;font-family:Space Mono,monospace">CHART SCREENSHOT</div>
            <img src="{screenshot_url}" style="width:100%;border-radius:4px;border:1px solid #1a2332" />
        </div>"""

    change_color = "#ff3355" if analysis.price_change < 0 else "#00ff88"
    change_sign = "+" if analysis.price_change >= 0 else ""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{analysis.symbol} · SMC Analysis</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Noto+Sans+TC:wght@300;400;700&family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#070a0f;color:#e8edf5;font-family:'Noto Sans TC',sans-serif;min-height:100vh}}
  body::before{{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,170,255,0.03)1px,transparent 1px),linear-gradient(90deg,rgba(0,170,255,0.03)1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}}
  .wrap{{max-width:800px;margin:0 auto;padding:24px 16px;position:relative;z-index:1}}
  @keyframes in{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
  .card{{background:#0d1117;border:1px solid #1a2332;border-radius:8px;padding:20px;margin-bottom:14px;animation:in .4s ease forwards;opacity:0}}
  .card:nth-child(1){{animation-delay:.05s;border-left:3px solid {border_color}}}
  .card:nth-child(2){{animation-delay:.1s}}
  .card:nth-child(3){{animation-delay:.15s}}
  .card:nth-child(4){{animation-delay:.2s}}
  .card:nth-child(5){{animation-delay:.25s}}
  .card:nth-child(6){{animation-delay:.3s}}
  .sec{{font-family:'Bebas Neue',sans-serif;font-size:11px;letter-spacing:3px;color:#4a5568;margin-bottom:12px}}
</style>
</head>
<body>
<div class="wrap">

  <!-- HEADER CARD -->
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">
      <div>
        <div style="font-size:10px;letter-spacing:3px;color:#00aaff;font-family:Space Mono,monospace;margin-bottom:4px">SMC SIGNAL ALERT</div>
        <div style="font-family:Space Mono,monospace;font-size:24px;font-weight:700">{analysis.symbol}</div>
        <div style="font-size:12px;color:#4a5568;margin-top:2px">{analysis.interval}m Chart · {now}</div>
      </div>
      <div style="text-align:right">
        <div style="font-family:Space Mono,monospace;font-size:22px;font-weight:700;color:{change_color}">{analysis.current_price:.2f}</div>
        <div style="font-family:Space Mono,monospace;font-size:13px;color:{change_color}">{change_sign}{analysis.price_change:.2f} ({change_sign}{analysis.price_change_pct:.2f}%)</div>
        <div style="margin-top:8px;display:inline-block;padding:4px 12px;border-radius:3px;background:{struct_color}1a;border:1px solid {struct_color}66;color:{struct_color};font-family:Space Mono,monospace;font-size:11px;font-weight:700">{analysis.market_structure.upper()}</div>
      </div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">{badges_html}</div>
  </div>

  <!-- SCREENSHOT -->
  {screenshot_section}

  <!-- SIGNALS -->
  <div class="card">
    <div class="sec">偵測到的 SMC 訊號</div>
    {signals_rows if signals_rows else '<div style="color:#4a5568;font-size:13px">本次掃描未偵測到明確訊號</div>'}
  </div>

  <!-- KEY LEVELS -->
  <div class="card">
    <div class="sec">關鍵價位</div>
    {key_levels_rows if key_levels_rows else '<div style="color:#4a5568;font-size:13px">無法識別關鍵價位</div>'}
  </div>

  <!-- ORDER BLOCKS + FVG -->
  {f'<div class="card"><div class="sec">Order Blocks</div>{ob_rows}</div>' if ob_rows else ''}

  <!-- RECOMMENDATION -->
  <div class="card">
    <div class="sec">操作建議</div>
    <div style="font-size:14px;line-height:1.9;color:rgba(232,237,245,0.8);font-weight:300;margin-bottom:12px">{analysis.recommendation or '暫無明確建議，持續觀察'}</div>
    {f'<div style="background:rgba(255,204,0,0.05);border:1px solid rgba(255,204,0,0.2);border-radius:4px;padding:10px 14px;font-size:12px;color:rgba(255,204,0,0.85)">⚠ {analysis.risk_note}</div>' if analysis.risk_note else ''}
  </div>

  <div style="text-align:center;padding:20px 0 8px;font-size:10px;color:#2d3748;font-family:Space Mono,monospace;letter-spacing:1px">
    SMC MONITOR · NOT FINANCIAL ADVICE
  </div>
</div>
</body>
</html>"""
