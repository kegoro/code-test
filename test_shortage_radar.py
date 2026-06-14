"""Tests for backend.shortage_radar — 缺貨雷達三階段強度模型。"""
from datetime import date

from backend.aistockmap_scraper import FocusItem
from backend.shortage_radar import (
    PRICING,
    REVENUE,
    SHORTAGE,
    evaluate_focus,
    format_radar_summary,
    scan_shortage,
)


REF = date(2026, 5, 16)


def _focus(
    title: str,
    description: str = "",
    date_label: str = "",
    tags: tuple[str, ...] = (),
    premium: bool = False,
) -> FocusItem:
    return FocusItem(
        source="test",
        date_label=date_label,
        title=title,
        description=description,
        industry_tags=tags,
        is_premium_locked=premium,
    )


# ── 階段偵測 ───────────────────────────────────────────────────────────────────

def test_shortage_only_hits_one_stage():
    sig = evaluate_focus(_focus("ABF 載板傳缺貨"), REF)
    assert sig.stages == frozenset({SHORTAGE})
    assert sig.chain_depth == 1
    assert sig.passed


def test_full_chain_hits_three_stages():
    sig = evaluate_focus(
        _focus("記憶體缺貨報價調漲，營收創高", date_label="2026-05-16"), REF
    )
    assert sig.stages == frozenset({SHORTAGE, PRICING, REVENUE})
    assert sig.chain_depth == 3


def test_no_keyword_does_not_pass():
    sig = evaluate_focus(_focus("某公司召開法說會"), REF)
    assert not sig.passed
    assert sig.score == 0.0
    assert sig.grade == "-"


# ── 強度排序：完整鏈 > 缺貨+漲價 > 單階段 ──────────────────────────────────────

def test_full_chain_scores_higher_than_shortage_plus_pricing():
    full = evaluate_focus(_focus("缺貨、漲價、營收暴衝", date_label="2026-05-16"), REF)
    two = evaluate_focus(_focus("缺貨、漲價", date_label="2026-05-16"), REF)
    one = evaluate_focus(_focus("傳出缺貨", date_label="2026-05-16"), REF)
    assert full.score > two.score > one.score


def test_shortage_plus_pricing_is_grade_a_when_fresh():
    sig = evaluate_focus(_focus("矽晶圓缺貨、報價調漲", date_label="2026-05-16"), REF)
    assert sig.grade == "A"


# ── 過水單（原則 E）─────────────────────────────────────────────────────────────

def test_revenue_only_is_watered_down_risk():
    sig = evaluate_focus(_focus("營收創高"), REF)
    assert REVENUE in sig.stages
    assert PRICING not in sig.stages
    assert sig.watered_down_risk is True


def test_revenue_with_low_margin_is_heavily_penalised():
    watered = evaluate_focus(_focus("營收暴增但毛利率下滑"), REF)
    pricing_backed = evaluate_focus(_focus("缺貨漲價帶動營收暴增"), REF)
    assert watered.watered_down_risk is True
    # 毛利轉弱的營收分數應遠低於有漲價撐腰的營收
    assert watered.score < pricing_backed.score


def test_revenue_with_pricing_not_watered():
    sig = evaluate_focus(_focus("缺貨漲價，營收暴衝"), REF)
    assert sig.watered_down_risk is False


# ── 新鮮度（§2.7.3）───────────────────────────────────────────────────────────

def test_fresh_today_beats_stale_old():
    fresh = evaluate_focus(_focus("面板缺貨漲價", date_label="2026-05-16"), REF)
    stale = evaluate_focus(_focus("面板缺貨漲價", date_label="2026-05-01"), REF)
    assert fresh.is_fresh is True
    assert stale.is_stale is True
    assert fresh.score > stale.score


def test_long_term_trend_word_marks_stale_even_if_today():
    sig = evaluate_focus(
        _focus("AI 長期趨勢帶動缺貨漲價", date_label="2026-05-16"), REF
    )
    assert sig.is_fresh is False
    assert sig.is_stale is True


def test_days_ago_phrase_parsed():
    sig = evaluate_focus(_focus("缺貨漲價", date_label="3 天前"), REF)
    assert sig.days_ago == 3


def test_unparseable_date_is_neutral():
    sig = evaluate_focus(_focus("缺貨漲價", date_label="近期"), REF)
    assert sig.days_ago is None


# ── 排序與摘要 ─────────────────────────────────────────────────────────────────

def test_scan_sorts_by_score_desc_and_keeps_unmatched_last():
    items = [
        _focus("無關題材"),
        _focus("傳缺貨"),
        _focus("缺貨漲價營收暴衝", date_label="2026-05-16"),
    ]
    out = scan_shortage(items, REF)
    assert out[0].focus.title == "缺貨漲價營收暴衝"
    assert out[-1].focus.title == "無關題材"
    assert not out[-1].passed


def test_summary_contains_header_and_grade():
    items = [_focus("矽晶圓缺貨報價調漲", date_label="2026-05-16")]
    out = scan_shortage(items, REF)
    text = format_radar_summary(out)
    assert "缺貨雷達" in text
    assert "[A" in text


def test_summary_empty_when_nothing_hits():
    out = scan_shortage([_focus("法說會")], REF)
    text = format_radar_summary(out)
    assert "今日無缺貨題材命中" in text
