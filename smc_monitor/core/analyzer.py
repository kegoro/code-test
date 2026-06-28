# ============================================================
#  core/analyzer.py
#  Claude Vision API 圖表分析模組
# ============================================================

import base64
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
import anthropic

from config.settings import ANTHROPIC_API_KEY, TARGET_SIGNALS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@dataclass
class SMCSignal:
    """單一 SMC 訊號"""
    type: str           # "BOS", "CHoCH", "Weak Low", "EQL", "FVG", "OB"
    direction: str      # "bearish" | "bullish" | "neutral"
    price_level: float  # 訊號發生的價格
    description: str    # 詳細說明


@dataclass
class ChartAnalysis:
    """完整圖表分析結果"""
    symbol: str
    interval: str
    timestamp: str

    # 基本價格資訊
    current_price: float = 0.0
    price_change: float = 0.0
    price_change_pct: float = 0.0

    # 偵測到的訊號
    signals: List[SMCSignal] = field(default_factory=list)
    has_alert_signal: bool = False   # 是否有需要立即通知的訊號

    # 關鍵價位
    premium_zone_top: float = 0.0
    premium_zone_bot: float = 0.0
    discount_zone_top: float = 0.0
    discount_zone_bot: float = 0.0
    equilibrium: float = 0.0

    weak_lows: List[float] = field(default_factory=list)
    weak_highs: List[float] = field(default_factory=list)
    order_blocks: List[dict] = field(default_factory=list)
    fvg_zones: List[dict] = field(default_factory=list)

    # 市場結構
    market_structure: str = "neutral"   # "bullish" | "bearish" | "neutral" | "ranging"
    trend_bias: str = "neutral"

    # 操作建議
    recommendation: str = ""
    risk_note: str = ""

    # 完整分析文字（Claude 原文）
    raw_analysis: str = ""


class ChartAnalyzer:
    """
    使用 Claude Vision API 分析 TradingView 截圖，
    識別 SMC 訊號並輸出結構化分析結果。
    """

    SYSTEM_PROMPT = """你是一位頂尖的 SMC（Smart Money Concept）技術分析師，
專門識別機構交易者的足跡。你的任務是分析 TradingView K 線圖截圖。

你必須：
1. 識別圖表中的所有 SMC 標籤（BOS / CHoCH / Weak Low / Weak High / EQL / FVG / OB）
2. 判斷當前市場結構（bullish / bearish / ranging）
3. 找出關鍵價位（Premium Zone, Discount Zone, Order Blocks, FVG）
4. 評估 Liquidity 分布（Weak Low 被清掃的可能性）
5. 給出具體的操作建議

輸出格式：請嚴格回傳 JSON，不要有任何額外文字。
"""

    USER_PROMPT_TEMPLATE = """請分析這張 {symbol} {interval}分鐘 K 線圖截圖。

重要：請以 JSON 格式回傳以下結構（所有 price 欄位填實際價格數字）：

{{
  "current_price": 0.0,
  "price_change": 0.0,
  "price_change_pct": 0.0,
  "market_structure": "bearish",
  "trend_bias": "bearish",
  "signals": [
    {{
      "type": "BOS",
      "direction": "bearish",
      "price_level": 36.50,
      "description": "向下突破結構，確認空頭"
    }}
  ],
  "has_alert_signal": true,
  "premium_zone_top": 0.0,
  "premium_zone_bot": 0.0,
  "discount_zone_top": 0.0,
  "discount_zone_bot": 0.0,
  "equilibrium": 0.0,
  "weak_lows": [35.00],
  "weak_highs": [],
  "order_blocks": [
    {{"type": "bearish_ob", "top": 37.50, "bot": 37.00, "description": "主要供給區"}}
  ],
  "fvg_zones": [
    {{"type": "bearish_fvg", "top": 36.80, "bot": 36.40, "filled": false}}
  ],
  "recommendation": "在回測 36.50 阻力時考慮做空，目標 35.00 Weak Low，止損 37.10 OB 上方",
  "risk_note": "若價格收回 36.50 以上，空單無效",
  "summary": "簡短的整體分析摘要（2-3句話）"
}}

偵測重點：{signals_to_detect}
"""

    async def analyze(self, screenshot_path: Path, symbol: str, interval: str) -> ChartAnalysis:
        """分析截圖，回傳結構化結果"""

        # 讀取截圖並轉 base64
        img_data = self._encode_image(screenshot_path)

        prompt = self.USER_PROMPT_TEMPLATE.format(
            symbol=symbol,
            interval=interval,
            signals_to_detect=", ".join(TARGET_SIGNALS),
        )

        try:
            response = client.messages.create(
                model="claude-opus-4-5",  # 用 Opus 提升圖像分析精準度
                max_tokens=2000,
                system=self.SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_data,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )

            raw_text = response.content[0].text
            data = self._parse_json_response(raw_text)
            analysis = self._build_analysis(data, symbol, interval, raw_text)

        except Exception as e:
            # 分析失敗時回傳最小結果（仍會推播截圖）
            analysis = ChartAnalysis(
                symbol=symbol,
                interval=interval,
                timestamp="",
                raw_analysis=f"分析失敗: {e}",
                has_alert_signal=False,
            )

        return analysis

    def _encode_image(self, path: Path) -> str:
        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _parse_json_response(self, text: str) -> dict:
        """從 Claude 回應中提取 JSON"""
        # 移除可能的 markdown code block
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()
        return json.loads(text)

    def _build_analysis(self, data: dict, symbol: str, interval: str, raw: str) -> ChartAnalysis:
        signals = [
            SMCSignal(
                type=s.get("type", ""),
                direction=s.get("direction", "neutral"),
                price_level=float(s.get("price_level", 0)),
                description=s.get("description", ""),
            )
            for s in data.get("signals", [])
        ]

        return ChartAnalysis(
            symbol=symbol,
            interval=interval,
            timestamp="",
            current_price=float(data.get("current_price", 0)),
            price_change=float(data.get("price_change", 0)),
            price_change_pct=float(data.get("price_change_pct", 0)),
            signals=signals,
            has_alert_signal=bool(data.get("has_alert_signal", False)),
            market_structure=data.get("market_structure", "neutral"),
            trend_bias=data.get("trend_bias", "neutral"),
            premium_zone_top=float(data.get("premium_zone_top", 0)),
            premium_zone_bot=float(data.get("premium_zone_bot", 0)),
            discount_zone_top=float(data.get("discount_zone_top", 0)),
            discount_zone_bot=float(data.get("discount_zone_bot", 0)),
            equilibrium=float(data.get("equilibrium", 0)),
            weak_lows=data.get("weak_lows", []),
            weak_highs=data.get("weak_highs", []),
            order_blocks=data.get("order_blocks", []),
            fvg_zones=data.get("fvg_zones", []),
            recommendation=data.get("recommendation", ""),
            risk_note=data.get("risk_note", ""),
            raw_analysis=raw,
        )
