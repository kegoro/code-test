"""
Tests for strategy/shortage_radar.py (pure functions, no I/O).
"""
import pandas as pd
import pytest
from strategy.shortage_radar import (
    detect_shortage, rank_signals, find_clusters,
    apply_cascade_bonus, find_rotation_candidates, ShortageSignal,
)


def _make_revenue_df(periods: list[str], revenues: list[float], yoys: list) -> pd.DataFrame:
    return pd.DataFrame({
        "period":  periods,
        "revenue": revenues,
        "yoy":     [float(y) if y is not None else float("nan") for y in yoys],
        "mom":     [None] * len(periods),
    })


def _make_sig(
    symbol: str, score: int, yoy: float = 25.0,
    sectors: list[str] | None = None,
    tier: str = "",
    consecutive: int = 2,
    acceleration: float = 5.0,
) -> ShortageSignal:
    s = ShortageSignal(
        symbol=symbol, name=symbol,
        latest_period="2026-04",
        latest_yoy=yoy, prev_yoy=yoy - acceleration,
        acceleration=acceleration,
        consecutive_above_20=consecutive,
        revenue_new_high=False,
        score=score,
        grade="強缺貨",
        tier=tier,
    )
    s.sectors = sectors or []
    return s


# ── detect_shortage ───────────────────────────────────────────────────────────

class TestDetectShortage:
    def test_returns_none_on_empty(self):
        assert detect_shortage("2330", "台積電", pd.DataFrame()) is None

    def test_returns_none_on_insufficient_yoy(self):
        df = _make_revenue_df(["2026-04"], [100_000], [None])
        assert detect_shortage("2330", "台積電", df) is None

    def test_basic_fields_populated(self):
        df = _make_revenue_df(
            ["2026-03", "2026-04"],
            [100_000, 120_000],
            [15.0, 22.0],
        )
        sig = detect_shortage("2330", "台積電", df)
        assert sig is not None
        assert sig.symbol == "2330"
        assert sig.name == "台積電"
        assert sig.latest_period == "2026-04"
        assert sig.latest_yoy == pytest.approx(22.0)
        assert sig.prev_yoy == pytest.approx(15.0)

    def test_score_increases_with_yoy(self):
        df_low = _make_revenue_df(["2026-03", "2026-04"], [100_000, 108_000], [5.0, 8.0])
        df_high = _make_revenue_df(["2026-03", "2026-04"], [100_000, 130_000], [15.0, 30.0])
        sig_low = detect_shortage("A", "A", df_low)
        sig_high = detect_shortage("B", "B", df_high)
        assert sig_high.score > sig_low.score

    def test_acceleration_positive_when_yoy_rising(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [10.0, 25.0])
        sig = detect_shortage("X", "X", df)
        assert sig.acceleration == pytest.approx(15.0)

    def test_acceleration_negative_when_yoy_falling(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [120_000, 100_000], [25.0, 10.0])
        sig = detect_shortage("X", "X", df)
        assert sig.acceleration == pytest.approx(-15.0)

    def test_strong_signal_gets_high_score(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000, 90_000, 110_000, 130_000],
            [15.0, 25.0, 30.0, 35.0],
        )
        sig = detect_shortage("2382", "廣達", df)
        assert sig.score >= 4
        assert sig.grade in ("強缺貨", "潛在缺貨")

    def test_grade_maps_correctly(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000, 90_000, 110_000, 130_000],
            [15.0, 25.0, 30.0, 35.0],
        )
        sig = detect_shortage("X", "X", df)
        if sig.score >= 4:
            assert sig.grade == "強缺貨"
        elif sig.score == 3:
            assert sig.grade == "潛在缺貨"
        elif sig.score == 2:
            assert sig.grade == "觀察中"
        else:
            assert sig.grade == "不符合"

    def test_revenue_new_high_detection(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000, 90_000, 95_000, 130_000],
            [10.0, 12.0, 15.0, 22.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.revenue_new_high is True

    def test_revenue_not_new_high_when_declining(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [130_000, 120_000, 110_000, 100_000],
            [10.0, 10.0, 10.0, 10.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.revenue_new_high is False

    def test_tier1_symbol_tagged_correctly(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("2330", "台積電", df)
        assert sig.tier == "tier1"

    def test_tier2_symbol_tagged_correctly(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("2303", "聯電", df)
        assert sig.tier == "tier2"

    def test_unknown_symbol_has_empty_tier(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("9999", "未知", df)
        assert sig.tier == ""
        assert sig.sectors == []

    def test_sectors_populated_for_known_symbol(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("2382", "廣達", df)
        assert len(sig.sectors) > 0

    def test_consecutive_above_20_counted(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000, 90_000, 110_000, 130_000],
            [25.0, 30.0, 35.0, 40.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.consecutive_above_20 == 4

    def test_score_minimum_1(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 95_000], [-5.0, -10.0])
        sig = detect_shortage("X", "X", df)
        assert sig.score >= 1

    def test_cascade_bonus_false_by_default(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("2303", "聯電", df)
        assert sig.cascade_bonus is False


# ── apply_cascade_bonus ───────────────────────────────────────────────────────

class TestCascadeBonus:
    def test_tier2_gets_bonus_when_tier1_is_hot(self):
        tier1 = _make_sig("2330", score=4, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("2303", score=3, sectors=["晶圓代工"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier2.cascade_bonus is True
        assert tier2.score == 4

    def test_tier2_grade_becomes_longhead_when_score_5(self):
        tier1 = _make_sig("2330", score=4, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("2303", score=4, sectors=["晶圓代工"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier2.score == 5
        assert tier2.grade == "龍頭瀑布"

    def test_tier2_no_bonus_when_tier1_not_hot(self):
        tier1 = _make_sig("2330", score=3, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("2303", score=3, sectors=["晶圓代工"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier2.cascade_bonus is False
        assert tier2.score == 3

    def test_tier1_not_affected_by_cascade(self):
        tier1 = _make_sig("2330", score=4, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("2303", score=3, sectors=["晶圓代工"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier1.cascade_bonus is False
        assert tier1.score == 4

    def test_cascade_limited_to_sector_match(self):
        tier1 = _make_sig("2330", score=4, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("6669", score=3, sectors=["AI散熱"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier2.cascade_bonus is False

    def test_score_cap_at_6(self):
        tier1 = _make_sig("2330", score=5, sectors=["晶圓代工"], tier="tier1")
        tier2 = _make_sig("2303", score=5, sectors=["晶圓代工"], tier="tier2")
        apply_cascade_bonus([tier1, tier2])
        assert tier2.score == 6

    def test_no_bonus_without_tier_info(self):
        tier1 = _make_sig("2330", score=4, sectors=["晶圓代工"], tier="tier1")
        unknown = _make_sig("9999", score=3, sectors=["晶圓代工"], tier="")
        apply_cascade_bonus([tier1, unknown])
        assert unknown.cascade_bonus is False


# ── find_rotation_candidates ──────────────────────────────────────────────────

class TestRotationCandidates:
    def test_laggard_flagged_when_leader_exists(self):
        # 東和鋼鐵已連續爆發（領先股），彰源剛加速（落後補漲）
        leader = _make_sig("2006", score=4, sectors=["鋼鐵/不鏽鋼"],
                           consecutive=4, acceleration=8.0)
        laggard = _make_sig("2030", score=3, sectors=["鋼鐵/不鏽鋼"],
                            consecutive=0, acceleration=12.0)
        find_rotation_candidates([leader, laggard])
        assert laggard.rotation_candidate is True
        assert laggard.rotation_leader == "2006"

    def test_leader_not_flagged_as_candidate(self):
        leader = _make_sig("2006", score=4, sectors=["鋼鐵/不鏽鋼"],
                           consecutive=4, acceleration=8.0)
        laggard = _make_sig("2030", score=3, sectors=["鋼鐵/不鏽鋼"],
                            consecutive=0, acceleration=12.0)
        find_rotation_candidates([leader, laggard])
        assert leader.rotation_candidate is False

    def test_no_candidate_without_leader(self):
        # 兩檔都剛加速、無人連續爆發 → 無領先股 → 不標記
        a = _make_sig("2030", score=3, sectors=["鋼鐵/不鏽鋼"],
                      consecutive=1, acceleration=10.0)
        b = _make_sig("2031", score=3, sectors=["鋼鐵/不鏽鋼"],
                      consecutive=1, acceleration=10.0)
        find_rotation_candidates([a, b])
        assert a.rotation_candidate is False
        assert b.rotation_candidate is False

    def test_laggard_needs_positive_acceleration(self):
        leader = _make_sig("2006", score=4, sectors=["鋼鐵/不鏽鋼"],
                           consecutive=4, acceleration=8.0)
        # 落後股動能向下 → 不算補漲
        falling = _make_sig("2030", score=3, sectors=["鋼鐵/不鏽鋼"],
                            consecutive=0, acceleration=-5.0)
        find_rotation_candidates([leader, falling])
        assert falling.rotation_candidate is False

    def test_already_running_stock_not_laggard(self):
        # 同族群兩檔都連續爆發 → 第二檔不算落後（consecutive 太高）
        leader = _make_sig("2006", score=4, sectors=["鋼鐵/不鏽鋼"],
                           consecutive=4, acceleration=8.0)
        also_running = _make_sig("2031", score=4, sectors=["鋼鐵/不鏽鋼"],
                                 consecutive=3, acceleration=5.0)
        find_rotation_candidates([leader, also_running])
        assert also_running.rotation_candidate is False

    def test_rotation_isolated_by_sector(self):
        leader = _make_sig("2006", score=4, sectors=["鋼鐵/不鏽鋼"],
                           consecutive=4, acceleration=8.0)
        # 不同族群的剛加速股，不該被鋼鐵領先股帶動
        other = _make_sig("3324", score=3, sectors=["AI散熱"],
                          consecutive=0, acceleration=12.0)
        find_rotation_candidates([leader, other])
        assert other.rotation_candidate is False


# ── rank_signals ──────────────────────────────────────────────────────────────

class TestRankSignals:
    def test_cascade_before_non_cascade(self):
        normal = _make_sig("A", score=5)
        cascade = _make_sig("B", score=4)
        cascade.cascade_bonus = True
        ranked = rank_signals([normal, cascade])
        assert ranked[0].symbol == "B"

    def test_sorted_by_score_desc_among_same_cascade(self):
        sigs = [_make_sig("A", 2), _make_sig("B", 5), _make_sig("C", 3)]
        ranked = rank_signals(sigs)
        assert ranked[0].score == 5
        assert ranked[-1].score == 2

    def test_tiebreak_by_yoy(self):
        sigs = [_make_sig("A", 4, yoy=20.0), _make_sig("B", 4, yoy=35.0)]
        ranked = rank_signals(sigs)
        assert ranked[0].latest_yoy == 35.0


# ── find_clusters ─────────────────────────────────────────────────────────────

class TestFindClusters:
    def test_cluster_requires_2_plus_symbols(self):
        sigs = [_make_sig("A", 4, sectors=["AI伺服器/ODM"]), _make_sig("B", 4, sectors=["AI伺服器/ODM"])]
        clusters = find_clusters(sigs)
        assert "AI伺服器/ODM" in clusters
        assert len(clusters["AI伺服器/ODM"]) == 2

    def test_single_symbol_not_a_cluster(self):
        sigs = [_make_sig("A", 4, sectors=["AI伺服器/ODM"])]
        assert find_clusters(sigs) == {}

    def test_low_score_excluded(self):
        sigs = [_make_sig("A", 4, sectors=["AI散熱"]), _make_sig("B", 2, sectors=["AI散熱"])]
        assert find_clusters(sigs) == {}

    def test_multiple_sectors(self):
        sigs = [
            _make_sig("A", 4, sectors=["AI伺服器/ODM", "AI散熱"]),
            _make_sig("B", 4, sectors=["AI伺服器/ODM"]),
            _make_sig("C", 4, sectors=["AI散熱"]),
        ]
        clusters = find_clusters(sigs)
        assert "AI伺服器/ODM" in clusters
        assert "AI散熱" in clusters
