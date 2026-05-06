"""
Tests for 5 new A+B+C strategy features.
Run: pytest tests/test_new_features.py -v
"""
import numpy as np
import pandas as pd
import pytest

from strategy.chip import (
    analyze_chip,
    _shareholding_stats,
    _avg_volume_5d,
    _contrarian_on_weak_market,
    MAJOR_HOLDER_THRESHOLD,
    MIN_VOLUME_LOTS,
)
from strategy.washout_detector import detect_washout, _detect_accumulation_on_decline
from strategy.signal import build_signal, _check_hard_conditions
from strategy.trend import TrendResult
from strategy.washout_detector import WashoutResult


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_trend(state="long_bull", price_above=True) -> TrendResult:
    return TrendResult(
        ma240_value=100.0, ma240_slope="up" if state == "long_bull" else "flat",
        state=state, deduction_value=95.0, deduction_drop_imminent=False,
        current_price=105.0 if price_above else 90.0, has_enough_data=True,
        price_above_ma240=price_above, ma20_slope="up", ma60_slope="up",
        higher_lows=True, higher_highs=True,
    )


def _make_institutional(net_values: list[int], name="外資") -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(net_values))
    return pd.DataFrame({"date": dates, "name": name, "net": net_values})


def _make_shareholding(ratios: list[float], counts: list[int]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(ratios), freq="7D")
    return pd.DataFrame({
        "date": dates,
        "major_holder_ratio": ratios,
        "shareholder_count": counts,
    })


def _make_prices_with_volume(
    n: int = 30, close_trend: str = "flat", vol_pattern: str = "normal"
) -> pd.DataFrame:
    closes = np.ones(n) * 100.0
    if close_trend == "down":
        closes = np.linspace(110, 90, n)
    elif close_trend == "up":
        closes = np.linspace(90, 110, n)

    volumes = np.ones(n) * 3000.0
    if vol_pattern == "quiet_end":
        # Last 8 days quiet AND above 2000 lots for H6 pass.
        # base=7000, quiet=2100 → avg20≈5040, threshold=2520 → 2100<2520 ✓
        # avg5d=2100 >= 2000 → H6 passes ✓
        volumes = np.ones(n) * 7000.0
        volumes[-8:] = 2100.0
    elif vol_pattern == "quiet_end_small":
        # Very quiet: below 2000 lots (for accum test ignoring H6)
        volumes[-8:] = 500.0
    elif vol_pattern == "low":
        volumes = np.ones(n) * 500.0

    dates = pd.date_range("2026-01-01", periods=n)
    return pd.DataFrame({"date": dates, "close": closes, "volume": volumes})


def _make_market_index(changes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(changes))
    closes = np.cumprod([1] + [1 + c for c in changes]) * 10000
    return pd.DataFrame({
        "date": dates,
        "taiex_close": closes[:len(changes)],
        "taiex_pct_change": [float("nan")] + list(changes[:-1]),
    })


def _empty_margin() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "margin_balance", "short_balance"])


# ── Feature 1: 大戶持股比例 >= 40% ──────────────────────────────────────────

class TestMajorHolderRatio:
    def test_ratio_above_threshold_passes(self):
        sh = _make_shareholding([0.45, 0.46, 0.47], [5000, 4900, 4800])
        ratio, _ = _shareholding_stats(sh)
        assert ratio == pytest.approx(0.47)

    def test_ratio_below_threshold_triggers_h5(self):
        trend = _make_trend()
        sh = _make_shareholding([0.35, 0.34, 0.33], [5000, 5100, 5200])
        prices = _make_prices_with_volume()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin(), shareholding=sh, prices=prices)
        assert chip.major_holder_ratio == pytest.approx(0.33)
        failed = _check_hard_conditions(trend, chip)
        assert any("H5" in f for f in failed)

    def test_no_data_skips_h5(self):
        """When shareholding data is missing, H5 must NOT trigger."""
        trend = _make_trend()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin(), shareholding=None)
        assert chip.major_holder_ratio == -1.0
        failed = _check_hard_conditions(trend, chip)
        assert not any("H5" in f for f in failed)

    def test_exactly_40_pct_passes(self):
        sh = _make_shareholding([0.40], [5000])
        ratio, _ = _shareholding_stats(sh)
        trend = _make_trend()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin(), shareholding=sh)
        failed = _check_hard_conditions(trend, chip)
        assert not any("H5" in f for f in failed)


# ── Feature 2: 股東人數下降 ──────────────────────────────────────────────────

class TestShareholderDeclining:
    def test_three_consecutive_declines(self):
        sh = _make_shareholding([0.50, 0.50, 0.50], [6000, 5500, 5000])
        _, declining = _shareholding_stats(sh)
        assert declining is True

    def test_not_consecutive_declines(self):
        sh = _make_shareholding([0.50, 0.50, 0.50], [5000, 5500, 5200])
        _, declining = _shareholding_stats(sh)
        assert declining is False

    def test_only_two_periods_not_enough(self):
        sh = _make_shareholding([0.50, 0.50], [6000, 5000])
        _, declining = _shareholding_stats(sh)
        assert declining is False

    def test_declining_adds_bonus(self):
        """Shareholder decline should give +1 to score."""
        from strategy.signal import _score
        trend = _make_trend()
        washout = WashoutResult(False, float("nan"), 0.0, "", False, 0, b2_breakout=False)

        sh_dec = _make_shareholding([0.50, 0.50, 0.50], [6000, 5500, 5000])
        sh_flat = _make_shareholding([0.50, 0.50, 0.50], [5000, 5000, 5000])
        inst = _make_institutional([100, 200, -50, 300, 400])

        chip_dec = analyze_chip(inst, _empty_margin(), shareholding=sh_dec)
        chip_flat = analyze_chip(inst, _empty_margin(), shareholding=sh_flat)

        assert _score(trend, chip_dec, washout) == _score(trend, chip_flat, washout) + 1


# ── Feature 3: 日成交量 >= 2000張 ────────────────────────────────────────────

class TestVolumeFilter:
    def test_above_2000_passes(self):
        prices = _make_prices_with_volume(vol_pattern="normal")  # 3000 lots
        avg_vol = _avg_volume_5d(prices)
        assert avg_vol >= MIN_VOLUME_LOTS

    def test_below_2000_triggers_h6(self):
        prices = _make_prices_with_volume(vol_pattern="low")  # 500 lots
        trend = _make_trend()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin(), prices=prices)
        assert chip.avg_volume_5d == pytest.approx(500.0)
        failed = _check_hard_conditions(trend, chip)
        assert any("H6" in f for f in failed)

    def test_no_volume_data_skips_h6(self):
        prices = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=10),
            "close": np.ones(10) * 100,
        })
        trend = _make_trend()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin(), prices=prices)
        assert chip.avg_volume_5d == -1.0
        failed = _check_hard_conditions(trend, chip)
        assert not any("H6" in f for f in failed)


# ── Feature 4: 大盤弱勢逆勢買超 ─────────────────────────────────────────────

class TestContrarianBuy:
    def test_foreign_buy_on_weak_day(self):
        # Market drops -2% on day 3, foreign buys that day
        inst = _make_institutional([100, -50, 300, 200, 100])
        index_changes = [-0.005, -0.003, -0.020, 0.005, 0.003]  # day 3 = -2%
        mi = _make_market_index(index_changes)
        # Align dates: inst day 3 (index 2) = 2026-01-03, market index day 3 = 2026-01-03
        # Both DataFrames use same date range so merge should work
        result = _contrarian_on_weak_market(inst, mi)
        assert result is True

    def test_no_contrarian_when_all_strong(self):
        inst = _make_institutional([100, 200, 300, 200, 100])
        index_changes = [0.005, 0.003, 0.020, 0.005, 0.003]  # all positive
        mi = _make_market_index(index_changes)
        result = _contrarian_on_weak_market(inst, mi)
        assert result is False

    def test_weak_market_but_foreign_selling(self):
        inst = _make_institutional([-100, -200, -300, -200, -100])
        index_changes = [-0.005, -0.010, -0.020, -0.005, -0.003]
        mi = _make_market_index(index_changes)
        result = _contrarian_on_weak_market(inst, mi)
        assert result is False

    def test_no_index_data_returns_false(self):
        inst = _make_institutional([100, 200, 300, 200, 100])
        result = _contrarian_on_weak_market(inst, None)
        assert result is False

    def test_contrarian_adds_2_bonus(self):
        """Contrarian buy on weak market should add +2 to score."""
        from strategy.signal import _score
        trend = _make_trend()
        washout = WashoutResult(False, float("nan"), 0.0, "", False, 0, b2_breakout=False)

        # Weak market day: market -2%, foreign buys
        inst = _make_institutional([100, -50, 300, 200, 100])
        index_changes = [-0.005, -0.003, -0.020, 0.005, 0.003]
        mi_weak = _make_market_index(index_changes)
        mi_none = None

        chip_contrarian = analyze_chip(inst, _empty_margin(), market_index=mi_weak)
        chip_normal = analyze_chip(inst, _empty_margin(), market_index=mi_none)

        assert chip_contrarian.contrarian_on_weak_market is True
        assert chip_normal.contrarian_on_weak_market is False
        assert _score(trend, chip_contrarian, washout) == _score(trend, chip_normal, washout) + 2


# ── Feature 5: 量縮吸籌識別 ──────────────────────────────────────────────────

class TestAccumulationOnDecline:
    def test_declining_price_quiet_volume_not_breaking_low(self):
        prices = _make_prices_with_volume(
            n=30, close_trend="down", vol_pattern="quiet_end"
        )
        closes = prices["close"].values
        volumes = prices["volume"].values
        result, days = _detect_accumulation_on_decline(closes, volumes)
        assert result == True  # noqa: E712 – avoid numpy bool `is` trap
        assert days >= 5

    def test_flat_price_not_detected_as_accumulation(self):
        prices = _make_prices_with_volume(
            n=30, close_trend="flat", vol_pattern="quiet_end"
        )
        closes = prices["close"].values
        volumes = prices["volume"].values
        result, days = _detect_accumulation_on_decline(closes, volumes)
        # Flat price slope ~0, not strictly declining
        assert result == False  # noqa: E712

    def test_insufficient_data_returns_false(self):
        closes = np.array([100.0, 99.0, 98.0])
        volumes = np.array([1000.0, 900.0, 800.0])
        result, days = _detect_accumulation_on_decline(closes, volumes)
        assert result is False

    def test_full_washout_result_includes_accumulation(self):
        prices = _make_prices_with_volume(
            n=30, close_trend="down", vol_pattern="quiet_end"
        )
        result = detect_washout(prices)
        assert hasattr(result, "accumulation_on_decline")
        assert hasattr(result, "accum_quiet_days")

    def test_accumulation_adds_bonus(self):
        """Accumulation on decline should add +1 to score."""
        from strategy.signal import _score
        trend = _make_trend()
        inst = _make_institutional([100, 200, -50, 300, 400])
        chip = analyze_chip(inst, _empty_margin())

        washout_with = WashoutResult(False, float("nan"), 0.0, "", True, 6, b2_breakout=False)
        washout_without = WashoutResult(False, float("nan"), 0.0, "", False, 0, b2_breakout=False)

        score_with = _score(trend, chip, washout_with)
        score_without = _score(trend, chip, washout_without)
        assert score_with == score_without + 1


# ── Integration: all conditions together ─────────────────────────────────────

class TestIntegration:
    def test_full_signal_with_all_new_features(self):
        from strategy.signal import build_signal
        from strategy.story_builder import build_story

        trend = _make_trend(state="turning_bull")
        # quiet_end: base=5000 lots, last 8 days=2200 lots → H6 passes (avg≥2000),
        # and 2200 < 50% of 5000 → accumulation_on_decline triggers
        prices = _make_prices_with_volume(n=30, close_trend="down", vol_pattern="quiet_end")
        inst = _make_institutional([100, -50, 300, 200, 500])
        sh = _make_shareholding([0.45, 0.44, 0.43], [6000, 5500, 5000])
        index_changes = [-0.005, -0.003, -0.020, 0.005, 0.003]
        mi = _make_market_index(index_changes)

        chip = analyze_chip(inst, _empty_margin(), shareholding=sh, market_index=mi, prices=prices)
        washout = detect_washout(prices)
        story = build_story("TEST", "測試股", trend, chip, washout)
        signal = build_signal("TEST", "測試股", trend, chip, washout, story)

        assert signal.hard_pass
        assert signal.abc_score >= 7
        assert signal.B1_chip["major_holder_ratio"] == pytest.approx(0.43)
        assert signal.B1_chip["shareholder_declining"] == True  # noqa: E712
        assert signal.B1_chip["contrarian_on_weak_market"] == True  # noqa: E712
        assert signal.washout["accumulation_on_decline"] == True  # noqa: E712

    def test_exclusion_when_low_volume_and_low_major_holder(self):
        from strategy.signal import build_signal
        from strategy.story_builder import build_story

        trend = _make_trend()
        prices = _make_prices_with_volume(vol_pattern="low")  # 500 lots
        inst = _make_institutional([100, 200, 300, 200, 100])
        sh = _make_shareholding([0.30], [10000])  # 30% < 40% threshold

        chip = analyze_chip(inst, _empty_margin(), shareholding=sh, prices=prices)
        washout = detect_washout(prices)
        story = build_story("TEST", "低流動性股", trend, chip, washout)
        signal = build_signal("TEST", "低流動性股", trend, chip, washout, story)

        assert not signal.hard_pass
        assert signal.recommendation == "排除"
        assert any("H5" in f for f in signal.failed_conditions)
        assert any("H6" in f for f in signal.failed_conditions)
