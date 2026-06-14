"""缺貨雷達 — 把雷老闆原則 A「缺貨哲學」升級成獨立的強度雷達。

theme_filter.py 的 `A_缺貨` 只是把缺貨/漲價/產能全部塞進「命中一次」的單一桶子，
無法分辨「只是傳缺貨」與「真缺貨→已漲價→營收暴衝」的強弱。

本模組把雷老闆原則 A 的因果鏈拆成三階段，照「走到哪一階」打強度分：

    缺貨 (SHORTAGE) → 漲價 (PRICING) → 營收暴衝 (REVENUE)

對應 LESSONS.md：
- §2.1 A「缺」字哲學：真缺貨 → 廠商漲價 → 營收暴衝。**漲價是「真缺貨」的確認**，
  所以漲價階段權重最高。
- §2.1 E 過水單陷阱：營收暴增但毛利低 = 假業績。所以「只有營收、沒有漲價」要降權，
  「營收 + 明講毛利率下滑」直接打成過水單風險。
- §2.7.3 當沖看「**今天剛爆**」的缺貨新聞（不是長期趨勢）→ 新鮮度加權。

設計與 theme_filter.py 一致：frozen dataclass + 純函式，方便單元測試與未來接 bot。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from backend.aistockmap_scraper import FocusItem


# ── 三階段因果鏈關鍵字 ─────────────────────────────────────────────────────────
# 同義詞用 tuple，命中任一個就算這組命中（記第一個同義詞作代表）。
SHORTAGE = "SHORTAGE"
PRICING = "PRICING"
REVENUE = "REVENUE"

STAGE_LABEL = {
    SHORTAGE: "缺貨",
    PRICING: "漲價",
    REVENUE: "營收暴衝",
}

# 三階段排序（畫鏈用）
STAGE_ORDER = (SHORTAGE, PRICING, REVENUE)

STAGE_KEYWORDS: dict[str, tuple[tuple[str, ...], ...]] = {
    SHORTAGE: (
        ("缺貨",), ("缺料",), ("短缺",), ("供不應求",), ("供應吃緊",),
        ("產能滿載",), ("產能吃緊",), ("產能滿到",),
        ("一機難求",), ("一料難求",), ("供需吃緊",),
        ("拉貨",), ("急單",), ("追單",), ("排隊",), ("塞單",),
        ("交期拉長", "交期延長"), ("缺口",),
    ),
    PRICING: (
        ("漲價",), ("調漲",), ("喊漲",), ("報價上揚", "報價走揚"),
        ("報價調升", "報價調漲"), ("價格上漲", "價格走揚"),
        ("漲幅",), ("漲勢",), ("惜售",), ("報價創高",),
        ("漲一波",), ("再漲",),
    ),
    REVENUE: (
        ("營收暴衝", "營收爆發"), ("營收創高", "營收新高", "營收創新高"),
        ("營收倍增", "營收翻倍"), ("營收大增", "營收暴增", "營收飆"),
        ("出貨爆發", "出貨大增", "出貨暴增"),
        ("獲利暴增", "獲利大增"), ("EPS 創高", "EPS創高", "EPS 新高"),
        ("業績爆發", "業績暴衝"), ("接單滿載", "訂單滿載"),
        ("能見度",), ("旺到",),
    ),
}

# 各階段基礎分：漲價權重最高（它是「真缺貨」的確認，原則 A）。
STAGE_POINTS: dict[str, float] = {
    SHORTAGE: 2.0,
    PRICING: 3.0,
    REVENUE: 2.0,
}

# 因果鏈加成
CHAIN_BONUS_SHORTAGE_PRICING = 2.0   # 缺貨 + 漲價 = 真缺貨有定價權（A 核心）
CHAIN_BONUS_FULL = 3.0               # 缺貨 + 漲價 + 營收 = 完整暴衝鏈

# 新鮮度乘數（§2.7.3 今天剛爆 vs 長期趨勢）
FRESH_MULTIPLIER = 1.25
STALE_MULTIPLIER = 0.6

# 過水單懲罰（原則 E）
WATERED_LOW_MARGIN_MULTIPLIER = 0.4   # 營收 + 明講毛利低 = 假業績
WATERED_NO_PRICING_MULTIPLIER = 0.8   # 只有營收沒有漲價 = 純看營收會被騙

# 等級門檻（套用所有乘數後的最終分）
GRADE_A_MIN = 8.0
GRADE_B_MIN = 5.0

# 新鮮度語意詞
_FRESH_WORDS = ("今日", "今天", "盤中", "剛", "最新", "突發", "急", "本週", "近日")
_STALE_WORDS = ("長期", "結構性", "趨勢", "未來幾年", "明年", "長線", "數年", "長線題材")

# 過水單：毛利轉弱語意（原則 E）
_LOW_MARGIN_WORDS = (
    "毛利率下滑", "毛利下滑", "毛利率衰退", "毛利率下降", "毛利率走低",
    "低毛利", "毛利率承壓", "毛利率縮", "賠本", "殺價",
)

# date_label 解析：抓 2026-05-16 / 2026/5/16 / 5/16 / 5月16日 / N 天前
_DATE_FULL_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DATE_MD_RE = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)")
_DATE_CN_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DAYS_AGO_RE = re.compile(r"(\d+)\s*天前")


@dataclass(frozen=True)
class StageHit:
    """一個階段的命中。"""

    stage: str  # SHORTAGE / PRICING / REVENUE
    matched_keywords: tuple[str, ...]


@dataclass(frozen=True)
class ShortageSignal:
    """一條經缺貨雷達評估後的訊號。"""

    focus: FocusItem
    stage_hits: tuple[StageHit, ...]
    score: float
    is_fresh: bool
    is_stale: bool
    watered_down_risk: bool
    days_ago: Optional[int]
    notes: tuple[str, ...]

    @property
    def stages(self) -> frozenset[str]:
        return frozenset(h.stage for h in self.stage_hits)

    @property
    def passed(self) -> bool:
        """至少命中一個階段才算進雷達。"""
        return len(self.stage_hits) > 0

    @property
    def grade(self) -> str:
        """A / B / C（未命中回 '-'）。"""
        if not self.passed:
            return "-"
        if self.score >= GRADE_A_MIN:
            return "A"
        if self.score >= GRADE_B_MIN:
            return "B"
        return "C"

    @property
    def chain_depth(self) -> int:
        """走到因果鏈第幾階（1=只有缺貨/3=完整鏈）。"""
        return len(self.stages & set(STAGE_ORDER))


# ── 文字掃描 ───────────────────────────────────────────────────────────────────

def _scan_stages(text: str) -> tuple[StageHit, ...]:
    if not text:
        return ()
    hits: list[StageHit] = []
    for stage in STAGE_ORDER:
        matched: list[str] = []
        for synonyms in STAGE_KEYWORDS[stage]:
            for term in synonyms:
                if term in text:
                    matched.append(synonyms[0])
                    break
        if matched:
            hits.append(StageHit(stage=stage, matched_keywords=tuple(matched)))
    return tuple(hits)


def _parse_days_ago(date_label: str, ref: date) -> Optional[int]:
    """從 date_label 解析「距 ref 幾天前」，無法解析回 None。"""
    if not date_label:
        return None
    m = _DAYS_AGO_RE.search(date_label)
    if m:
        return int(m.group(1))
    if "今天" in date_label or "今日" in date_label:
        return 0
    if "昨天" in date_label or "昨日" in date_label:
        return 1

    parsed: Optional[date] = None
    m = _DATE_FULL_RE.search(date_label)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        parsed = _safe_date(y, mo, d)
    if parsed is None:
        m = _DATE_CN_RE.search(date_label)
        if m:
            parsed = _safe_date(ref.year, int(m.group(1)), int(m.group(2)))
    if parsed is None:
        m = _DATE_MD_RE.search(date_label)
        if m:
            parsed = _safe_date(ref.year, int(m.group(1)), int(m.group(2)))

    if parsed is None:
        return None
    delta = (ref - parsed).days
    # 解析出未來日期（多半是年份猜錯）視為無效
    return delta if delta >= 0 else None


def _safe_date(y: int, mo: int, d: int) -> Optional[date]:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _assess_freshness(text: str, days_ago: Optional[int]) -> tuple[bool, bool]:
    """回 (is_fresh, is_stale)。日期優先，無日期才看語意詞。"""
    has_stale_word = any(w in text for w in _STALE_WORDS)
    has_fresh_word = any(w in text for w in _FRESH_WORDS)

    if days_ago is not None:
        if days_ago <= 1:
            # 今天/昨天爆 → 新鮮，但若明講長期趨勢則不算「剛爆」
            return (not has_stale_word, has_stale_word)
        if days_ago >= 4:
            return (False, True)
        # 2-3 天：語意詞決定
        return (has_fresh_word and not has_stale_word, has_stale_word)

    # 無日期：純看語意
    if has_stale_word and not has_fresh_word:
        return (False, True)
    if has_fresh_word and not has_stale_word:
        return (True, False)
    return (False, False)


# ── 評分 ───────────────────────────────────────────────────────────────────────

def _score_signal(
    stage_hits: tuple[StageHit, ...],
    text: str,
    is_fresh: bool,
    is_stale: bool,
) -> tuple[float, bool, tuple[str, ...]]:
    """回 (score, watered_down_risk, notes)。"""
    if not stage_hits:
        return (0.0, False, ())

    stages = {h.stage for h in stage_hits}
    notes: list[str] = []

    raw = sum(STAGE_POINTS[h.stage] for h in stage_hits)

    if SHORTAGE in stages and PRICING in stages:
        raw += CHAIN_BONUS_SHORTAGE_PRICING
        notes.append("缺貨+漲價：真缺貨有定價權（原則 A 核心）")
    if {SHORTAGE, PRICING, REVENUE} <= stages:
        raw += CHAIN_BONUS_FULL
        notes.append("完整因果鏈 缺貨→漲價→營收暴衝")

    # 過水單檢查（原則 E）— 只在有營收階段時評估
    watered = False
    if REVENUE in stages:
        has_low_margin = any(w in text for w in _LOW_MARGIN_WORDS)
        if has_low_margin:
            raw *= WATERED_LOW_MARGIN_MULTIPLIER
            watered = True
            notes.append("⚠️ 過水單風險：營收暴增但提到毛利轉弱（原則 E）")
        elif PRICING not in stages:
            raw *= WATERED_NO_PRICING_MULTIPLIER
            watered = True
            notes.append("⚠️ 只有營收沒漲價：純看營收易被過水單騙（原則 E）")

    # 新鮮度（§2.7.3）
    if is_fresh:
        raw *= FRESH_MULTIPLIER
        notes.append("🔥 今天剛爆，當沖題材")
    elif is_stale:
        raw *= STALE_MULTIPLIER
        notes.append("🐢 偏長期趨勢，當沖時框不對")

    return (round(raw, 2), watered, tuple(notes))


def evaluate_focus(item: FocusItem, ref_date: Optional[date] = None) -> ShortageSignal:
    """對單一 FocusItem 跑缺貨雷達評估。"""
    ref = ref_date or date.today()
    text = " ".join(
        [item.title, item.description, " ".join(item.industry_tags)]
    )
    stage_hits = _scan_stages(text)
    days_ago = _parse_days_ago(item.date_label, ref)
    is_fresh, is_stale = _assess_freshness(text, days_ago)
    score, watered, notes = _score_signal(stage_hits, text, is_fresh, is_stale)
    return ShortageSignal(
        focus=item,
        stage_hits=stage_hits,
        score=score,
        is_fresh=is_fresh,
        is_stale=is_stale,
        watered_down_risk=watered,
        days_ago=days_ago,
        notes=notes,
    )


def scan_shortage(
    items: Iterable[FocusItem], ref_date: Optional[date] = None
) -> tuple[ShortageSignal, ...]:
    """掃一批題材，依分數降序排列（命中的在前，未命中保留原序在後）。"""
    items_list = list(items)
    signals = [evaluate_focus(it, ref_date) for it in items_list]
    # 穩定排序：先依 passed，再依 score 降序，平手保留原順序
    indexed = list(enumerate(signals))
    indexed.sort(key=lambda pair: (not pair[1].passed, -pair[1].score, pair[0]))
    return tuple(sig for _, sig in indexed)


# ── Telegram 簡短摘要 ──────────────────────────────────────────────────────────

def _chain_diagram(stages: frozenset[str]) -> str:
    """畫因果鏈：命中的階段亮、未命中的灰。"""
    parts = []
    for stage in STAGE_ORDER:
        label = STAGE_LABEL[stage]
        parts.append(label if stage in stages else f"·{label}·")
    return " → ".join(parts)


def format_radar_summary(signals: Iterable[ShortageSignal]) -> str:
    """產 Telegram 缺貨雷達列點訊息。"""
    sig_list = list(signals)
    passed = [s for s in sig_list if s.passed]
    grade_emoji = {"A": "🟢", "B": "🟡", "C": "⚪"}

    lines: list[str] = []
    lines.append("📡 缺貨雷達 — 雷老闆原則 A 強度掃描")
    lines.append("")
    lines.append(f"命中 {len(passed)}/{len(sig_list)} 條（缺貨→漲價→營收暴衝）")
    lines.append("")

    if not passed:
        lines.append("（今日無缺貨題材命中）")
        return "\n".join(lines)

    for i, s in enumerate(passed, 1):
        emoji = grade_emoji.get(s.grade, "⚪")
        flags = ""
        if s.is_fresh:
            flags += " 🔥"
        if s.watered_down_risk:
            flags += " ⚠️過水單"
        lock = " 🔒" if s.focus.is_premium_locked else ""
        lines.append(f"{i}. {emoji} {s.focus.title} [{s.grade} {s.score}]{flags}{lock}")
        lines.append(f"   {_chain_diagram(s.stages)}")
        kw = " / ".join(
            f"{STAGE_LABEL[h.stage]}：{'、'.join(h.matched_keywords)}"
            for h in s.stage_hits
        )
        lines.append(f"   命中：{kw}")
        tags = "、".join(s.focus.industry_tags)
        if tags:
            lines.append(f"   產業：{tags}")
        lines.append("")

    lines.append("🟢A 真缺貨有定價權　🟡B 部分鏈　⚪C 僅傳聞")
    lines.append("→ A 級可考慮 /wl_add <股號> 進當沖 watchlist")
    return "\n".join(lines)
