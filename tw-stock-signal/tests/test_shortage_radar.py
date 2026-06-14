"""
Tests for strategy/shortage_radar.py (pure functions, no I/O).
"""
import pandas as pd
import pytest
from strategy.shortage_radar import detect_shortage, rank_signals, find_clusters, ShortageSignal


def _make_revenue_df(periods: list[str], revenues: list[float], yoys: list) -> pd.DataFrame:
    return pd.DataFrame({
        "period":  periods,
        "revenue": revenues,
        "yoy":     [float(y) if y is not None else float("nan") for y in yoys],
        "mom":     [None] * len(periods),
    })


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
        df = _make_revenue_df(
            ["2026-03", "2026-04"],
            [100_000, 120_000],
            [10.0, 25.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.acceleration == pytest.approx(15.0)

    def test_acceleration_negative_when_yoy_falling(self):
        df = _make_revenue_df(
            ["2026-03", "2026-04"],
            [120_000, 100_000],
            [25.0, 10.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.acceleration == pytest.approx(-15.0)

    def test_strong_signal_gets_high_score(self):
        """YoY >= 20%, accelerating, 3 consecutive months > 20%, new high → score 5"""
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000,   90_000,   110_000,  130_000],
            [15.0,     25.0,      30.0,     35.0],
        )
        sig = detect_shortage("2382", "廣達", df)
        assert sig.score >= 4
        assert sig.grade in ("強缺貨", "潛在缺貨")

    def test_grade_maps_correctly(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000,   90_000,   110_000,  130_000],
            [15.0,     25.0,      30.0,     35.0],
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
            [80_000,   90_000,   95_000,   130_000],  # 130k is new high
            [10.0,     12.0,     15.0,     22.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.revenue_new_high is True

    def test_revenue_not_new_high_when_declining(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [130_000,  120_000,  110_000,  100_000],  # declining
            [10.0,     10.0,     10.0,     10.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.revenue_new_high is False

    def test_sectors_populated_for_known_symbol(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("2382", "廣達", df)
        assert len(sig.sectors) > 0  # 2382 is in multiple sectors

    def test_sectors_empty_for_unknown_symbol(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 120_000], [15.0, 22.0])
        sig = detect_shortage("9999", "未知", df)
        assert sig.sectors == []

    def test_consecutive_above_20_counted(self):
        df = _make_revenue_df(
            ["2026-01", "2026-02", "2026-03", "2026-04"],
            [80_000,   90_000,   110_000,  130_000],
            [25.0,     30.0,     35.0,     40.0],
        )
        sig = detect_shortage("X", "X", df)
        assert sig.consecutive_above_20 == 4

    def test_score_minimum_1(self):
        df = _make_revenue_df(["2026-03", "2026-04"], [100_000, 95_000], [-5.0, -10.0])
        sig = detect_shortage("X", "X", df)
        assert sig.score >= 1


# ── rank_signals ──────────────────────────────────────────────────────────────

class TestRankSignals:
    def _make_sig(self, score: int, yoy: float) -> ShortageSignal:
        return ShortageSignal(
            symbol="X", name="X",
            latest_period="2026-04",
            latest_yoy=yoy, prev_yoy=None,
            acceleration=None,
            consecutive_above_20=0,
            revenue_new_high=False,
            score=score, grade="觀察中",
        )

    def test_sorted_by_score_desc(self):
        sigs = [self._make_sig(2, 15.0), self._make_sig(5, 30.0), self._make_sig(3, 20.0)]
        ranked = rank_signals(sigs)
        assert ranked[0].score == 5
        assert ranked[-1].score == 2

    def test_tiebreak_by_yoy(self):
        sigs = [self._make_sig(4, 20.0), self._make_sig(4, 35.0)]
        ranked = rank_signals(sigs)
        assert ranked[0].latest_yoy == 35.0


# ── find_clusters ─────────────────────────────────────────────────────────────

class TestFindClusters:
    def _sig(self, symbol: str, score: int, sectors: list[str]) -> ShortageSignal:
        s = ShortageSignal(
            symbol=symbol, name=symbol,
            latest_period="2026-04",
            latest_yoy=25.0, prev_yoy=None,
            acceleration=1.0,
            consecutive_above_20=2,
            revenue_new_high=False,
            score=score, grade="強缺貨",
        )
        s.sectors = sectors
        return s

    def test_cluster_requires_2_plus_symbols(self):
        sigs = [self._sig("A", 4, ["AI伺服器/ODM"]), self._sig("B", 4, ["AI伺服器/ODM"])]
        clusters = find_clusters(sigs)
        assert "AI伺服器/ODM" in clusters
        assert len(clusters["AI伺服器/ODM"]) == 2

    def test_single_symbol_not_a_cluster(self):
        sigs = [self._sig("A", 4, ["AI伺服器/ODM"])]
        clusters = find_clusters(sigs)
        assert clusters == {}

    def test_low_score_signals_excluded_from_cluster(self):
        sigs = [self._sig("A", 4, ["AI散熱"]), self._sig("B", 2, ["AI散熱"])]
        clusters = find_clusters(sigs)
        assert clusters == {}

    def test_multiple_sectors(self):
        sigs = [
            self._sig("A", 4, ["AI伺服器/ODM", "AI散熱"]),
            self._sig("B", 4, ["AI伺服器/ODM"]),
            self._sig("C", 4, ["AI散熱"]),
        ]
        clusters = find_clusters(sigs)
        assert "AI伺服器/ODM" in clusters
        assert "AI散熱" in clusters
