"""雷老闆 A/B 原則題材過濾器。

把 aistockmap 抓回來的 FocusItem 用 5 類關鍵字打標：
  A   缺貨類       — 缺貨 → 漲價 → 營收暴衝
  B1  大客戶       — Apple/微軟/輝達/Meta/CSP 等
  B2  新產品       — Blackwell/Rubin/H200/GB300 等下一代旗艦
  B3  新政策       — 補助/制裁/晶片法案/出口管制
  B4  新技術       — CPO/HBM/CoWoS/2nm/玻璃基板/液冷

對應 LESSONS.md §2.1：「大戶買激情股不買牛皮股，要有大客戶/新產品/新政策/新技術其中一個」。
題材命中越多原則 → 分數越高 → 越值得進白名單。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.aistockmap_scraper import FocusItem


# ── 關鍵字字典 ─────────────────────────────────────────────────────────────────
# 同義詞用 tuple，命中任一個就算這個關鍵字命中
KEYWORDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "A_缺貨": (
        ("缺貨",), ("缺料",), ("短缺",), ("供不應求",), ("供應吃緊",),
        ("漲價",), ("調漲",), ("報價上揚",),
        ("擴產",), ("產能滿載",), ("產能吃緊",),
        ("能見度",), ("訂單滿到", "訂單能見度"),
        ("需求爆發",), ("需求強勁",), ("一機難求",),
    ),
    "B1_大客戶": (
        ("Apple", "蘋果"), ("Microsoft", "微軟"), ("Google", "谷歌", "Alphabet"),
        ("NVIDIA", "輝達"), ("Meta", "臉書"), ("Amazon", "亞馬遜", "AWS"),
        ("Tesla", "特斯拉"), ("OpenAI",),
        ("台積電", "TSMC"), ("鴻海",), ("廣達",), ("聯發科",),
        ("三星", "Samsung"), ("Intel", "英特爾"), ("AMD",), ("Broadcom", "博通"),
        ("CSP", "雲端服務供應商", "雲端大廠"), ("Hyperscaler", "超大規模"),
    ),
    "B2_新產品": (
        ("Blackwell",), ("Rubin",), ("Hopper",),
        ("H100",), ("H200",), ("GB200",), ("GB300",),
        ("MI300",), ("MI325", "MI350"),
        ("新世代", "下一代", "next-gen", "Next-Gen"),
        ("新品",), ("新平台",),
    ),
    "B3_新政策": (
        ("補助", "補貼"), ("禁令",), ("制裁",), ("關稅",),
        ("晶片法案", "CHIPS Act", "CHIPS"),
        ("出口管制",), ("實體清單",), ("商務部",),
        ("投審會",), ("法規",),
    ),
    "B4_新技術": (
        ("CPO",), ("矽光子",), ("光學互連",),
        ("液冷",), ("浸沒式",),
        ("HBM",),
        ("先進封裝",), ("CoWoS",), ("FOPLP",), ("SoIC",),
        ("2nm", "2 奈米"), ("3nm", "3 奈米"),
        ("玻璃基板",), ("3D 整合", "3D 堆疊", "3D-IC"),
        ("先進製程",), ("異質整合",),
        ("ASIC", "客製化晶片", "自研晶片"),
    ),
}


@dataclass(frozen=True)
class HitReason:
    """一次關鍵字命中。"""

    category: str  # "A_缺貨" / "B1_大客戶" / "B2_新產品" / "B3_新政策" / "B4_新技術"
    matched_keywords: tuple[str, ...]


@dataclass(frozen=True)
class FilteredFocus:
    """經過雷老闆 A/B 原則過濾後的題材。"""

    focus: FocusItem
    hits: tuple[HitReason, ...]

    @property
    def score(self) -> int:
        """命中的原則類別數（不重複計算同一類別內的關鍵字）。"""
        return len(self.hits)

    @property
    def passed(self) -> bool:
        """至少命中 1 個雷老闆 A/B 原則才算通過。"""
        return self.score > 0


def _scan_text(text: str) -> tuple[HitReason, ...]:
    """掃單一文字字串，回傳所有命中類別。"""
    if not text:
        return ()
    hits: list[HitReason] = []
    for category, keyword_groups in KEYWORDS.items():
        matched: list[str] = []
        for synonyms in keyword_groups:
            for term in synonyms:
                if term in text:
                    # 命中一個就算這組命中，記錄第一個同義詞作代表
                    matched.append(synonyms[0])
                    break
        if matched:
            hits.append(HitReason(category=category, matched_keywords=tuple(matched)))
    return tuple(hits)


def filter_focus_items(items: Iterable[FocusItem]) -> tuple[FilteredFocus, ...]:
    """過濾並依分數降序排列。"""
    scored: list[FilteredFocus] = []
    for item in items:
        # 用 title + description + tags 拼起來掃
        text = " ".join([item.title, item.description, " ".join(item.industry_tags)])
        hits = _scan_text(text)
        scored.append(FilteredFocus(focus=item, hits=hits))
    # 排序：通過的依分數降序在前，未通過的在後保留原順序
    scored.sort(key=lambda f: (-f.score, items_index(items, f)))
    return tuple(scored)


def items_index(items: Iterable[FocusItem], target: FilteredFocus) -> int:
    for idx, it in enumerate(items):
        if it is target.focus:
            return idx
    return 9999


def format_short_summary(filtered: Iterable[FilteredFocus]) -> str:
    """產 Telegram 簡短列點訊息（不含 HTML 報告本身）。"""
    filtered_list = list(filtered)
    passed = [f for f in filtered_list if f.passed]
    skipped = [f for f in filtered_list if not f.passed]

    lines: list[str] = []
    lines.append(f"📰 aistockmap 每日題材掃描")
    lines.append("")
    lines.append(f"🔥 命中題材（{len(passed)}/{len(filtered_list)}）：")
    lines.append("")
    for i, f in enumerate(passed, 1):
        stars = "⭐" * min(f.score, 5)
        hit_summary = " | ".join(
            f"{h.category}({','.join(h.matched_keywords)})" for h in f.hits
        )
        tags = "、".join(f.focus.industry_tags) or "—"
        lock = "🔒" if f.focus.is_premium_locked else ""
        lines.append(f"{i}. {f.focus.title} {stars}{lock}")
        lines.append(f"   命中：{hit_summary}")
        lines.append(f"   產業：{tags}")
        lines.append("")
    if skipped:
        lines.append(f"⏸ 跳過題材（{len(skipped)}/{len(filtered_list)}）：")
        for f in skipped:
            lines.append(f"  - {f.focus.title}（無雷老闆 A/B 命中）")
    return "\n".join(lines)
