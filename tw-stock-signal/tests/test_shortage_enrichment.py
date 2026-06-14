"""
Tests for strategy/shortage_enrichment.py (pure functions, no I/O).
"""
import pandas as pd
import numpy as np
import pytest
from strategy.shortage_enrichment import (
    enrich_shortage_signal, EnrichmentResult,
    _gross_margin_analysis, _capex_analysis, _contract_liability_analysis,
    _pe_analysis, _inventory_analysis,
)


def _inc(revs: list[float], cogs: list[float]) -> pd.DataFrame:
    """Build wide income statement with Revenue + CostOfGoodsSold."""
    idx = pd.date_range("2023-01-01", periods=len(revs), freq="QE")
    return pd.DataFrame({"Revenue": revs, "CostOfGoodsSold": cogs}, index=idx)


def _cf(ppe_values: list[float]) -> pd.DataFrame:
    """Build wide cash flow with PP&E (negative = buying machines)."""
    idx = pd.date_range("2023-01-01", periods=len(ppe_values), freq="QE")
    return pd.DataFrame({"PropertyAndPlantAndEquipment": ppe_values}, index=idx)


def _bal(cl_values: list[float]) -> pd.DataFrame:
    """Build wide balance sheet with ContractLiabilities."""
    idx = pd.date_range("2023-01-01", periods=len(cl_values), freq="QE")
    return pd.DataFrame({"ContractLiabilities": cl_values}, index=idx)


def _bal_inv(inv_values: list[float]) -> pd.DataFrame:
    """Build wide balance sheet with Inventories."""
    idx = pd.date_range("2023-01-01", periods=len(inv_values), freq="QE")
    return pd.DataFrame({"Inventories": inv_values}, index=idx)


def _per(values: list[float]) -> pd.DataFrame:
    """Build PER DataFrame (raw FinMind style with PER column)."""
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"PER": values}, index=idx)


# ── _gross_margin_analysis ────────────────────────────────────────────────────

class TestGrossMarginAnalysis:
    def test_returns_unknown_on_empty(self):
        gm, trend = _gross_margin_analysis(pd.DataFrame())
        assert gm is None
        assert trend == "unknown"

    def test_expanding_margin_trend_up(self):
        # Margin goes: 20% → 25% → 30% → 35% (steadily up)
        revs = [100, 100, 100, 100, 100, 100]
        cogs = [80, 78, 75, 72, 68, 65]
        _, trend = _gross_margin_analysis(_inc(revs, cogs))
        assert trend == "up"

    def test_contracting_margin_trend_down(self):
        # Margin goes from 35% → 20% (falling)
        revs = [100, 100, 100, 100, 100, 100]
        cogs = [65, 68, 72, 75, 78, 80]
        _, trend = _gross_margin_analysis(_inc(revs, cogs))
        assert trend == "down"

    def test_stable_margin(self):
        revs = [100] * 6
        cogs = [70] * 6
        gm, trend = _gross_margin_analysis(_inc(revs, cogs))
        assert trend == "flat"
        assert gm == pytest.approx(30.0)

    def test_correct_gm_calculation(self):
        revs = [200, 200]
        cogs = [150, 150]
        gm, _ = _gross_margin_analysis(_inc(revs, cogs))
        assert gm == pytest.approx(25.0)


# ── _capex_analysis ───────────────────────────────────────────────────────────

class TestCapexAnalysis:
    def test_returns_unknown_on_empty(self):
        yoy, flag = _capex_analysis(pd.DataFrame())
        assert yoy is None
        assert flag == "unknown"

    def test_expanding_capex(self):
        # 買機台暴增：從 -100 to -200 (YoY +100%)
        ppe = [-100, -110, -120, -130, -200]
        _, flag = _capex_analysis(_cf(ppe))
        assert flag == "expanding"

    def test_stable_capex(self):
        ppe = [-100, -102, -98, -101, -100]
        _, flag = _capex_analysis(_cf(ppe))
        assert flag == "stable"

    def test_shrinking_capex(self):
        ppe = [-200, -180, -160, -140, -100]
        _, flag = _capex_analysis(_cf(ppe))
        assert flag == "shrinking"

    def test_positive_ppe_values_also_handled(self):
        # Some FinMind formats may return positive outflows
        ppe = [100, 110, 120, 130, 200]
        yoy, flag = _capex_analysis(_cf(ppe))
        assert flag == "expanding"
        assert yoy is not None and yoy > 0

    def test_insufficient_data_returns_unknown(self):
        ppe = [-100, -110]
        _, flag = _capex_analysis(_cf(ppe))
        assert flag == "unknown"


# ── _contract_liability_analysis ──────────────────────────────────────────────

class TestContractLiabilityAnalysis:
    def test_returns_unknown_on_empty(self):
        yoy, flag = _contract_liability_analysis(pd.DataFrame())
        assert yoy is None
        assert flag == "unknown"

    def test_strong_growth_with_absolute_threshold(self):
        # +60% YoY AND cl (160) >= monthly_revenue*2 (70*2=140)
        cl = [100, 110, 120, 130, 160]
        _, flag = _contract_liability_analysis(_bal(cl), latest_monthly_revenue=70)
        assert flag == "strong"

    def test_high_yoy_without_absolute_threshold_is_growing(self):
        # +60% YoY but no monthly revenue context → "growing" not "strong"
        cl = [100, 110, 120, 130, 160]
        _, flag = _contract_liability_analysis(_bal(cl))
        assert flag == "growing"

    def test_growing(self):
        cl = [100, 104, 108, 112, 115]   # ~+15% YoY
        _, flag = _contract_liability_analysis(_bal(cl))
        assert flag == "growing"

    def test_flat(self):
        cl = [100, 101, 99, 100, 100]
        _, flag = _contract_liability_analysis(_bal(cl))
        assert flag == "flat"

    def test_insufficient_data(self):
        cl = [100, 110]
        _, flag = _contract_liability_analysis(_bal(cl))
        assert flag == "unknown"


# ── _pe_analysis ──────────────────────────────────────────────────────────────

class TestPEAnalysis:
    def test_returns_unknown_on_empty(self):
        per_val, flag = _pe_analysis(pd.DataFrame())
        assert per_val is None
        assert flag == "unknown"

    def test_cheap_per(self):
        per_val, flag = _pe_analysis(_per([8.5]))
        assert flag == "cheap"
        assert per_val == pytest.approx(8.5)

    def test_sweet_spot_lower_bound(self):
        _, flag = _pe_analysis(_per([10.0]))
        assert flag == "sweet_spot"

    def test_sweet_spot_upper_bound(self):
        _, flag = _pe_analysis(_per([15.0]))
        assert flag == "sweet_spot"

    def test_fair_valuation(self):
        _, flag = _pe_analysis(_per([20.0]))
        assert flag == "fair"

    def test_expensive(self):
        per_val, flag = _pe_analysis(_per([30.0]))
        assert flag == "expensive"
        assert per_val == pytest.approx(30.0)

    def test_negative_per_returns_unknown(self):
        # Loss-making stock → PER negative
        per_val, flag = _pe_analysis(_per([-5.0]))
        assert per_val is None
        assert flag == "unknown"

    def test_extremely_high_per_returns_unknown(self):
        # Unreliable value (e.g., near-zero earnings)
        per_val, flag = _pe_analysis(_per([500.0]))
        assert per_val is None
        assert flag == "unknown"

    def test_uses_latest_value(self):
        # Should use the last row, not the first
        _, flag = _pe_analysis(_per([50.0, 30.0, 12.0]))
        assert flag == "sweet_spot"


# ── _inventory_analysis ───────────────────────────────────────────────────────

class TestInventoryAnalysis:
    def test_returns_unknown_on_empty(self):
        inv_yoy, flag = _inventory_analysis(pd.DataFrame())
        assert inv_yoy is None
        assert flag == "unknown"

    def test_insufficient_data_returns_unknown(self):
        inv_yoy, flag = _inventory_analysis(_bal_inv([100, 110]), revenue_yoy=20.0)
        assert flag == "unknown"

    def test_healthy_buildup(self):
        # Revenue up (yoy=+25%), inventory up +30% → healthy
        inv = [100, 105, 110, 120, 130]
        inv_yoy, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=25.0)
        assert flag == "healthy_buildup"
        assert inv_yoy == pytest.approx(30.0)

    def test_tight_supply(self):
        # Revenue up (yoy=+20%), inventory down → supply吃緊
        inv = [100, 95, 90, 88, 80]
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=20.0)
        assert flag == "tight_supply"

    def test_channel_stuffing(self):
        # Revenue down (yoy=-10%), inventory up >20% → 塞貨地雷
        inv = [100, 110, 118, 122, 130]
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=-10.0)
        assert flag == "channel_stuffing"

    def test_over_stocked(self):
        # Revenue up but inventory surges >60% → 備料過頭
        inv = [100, 120, 140, 155, 170]
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=20.0)
        assert flag == "over_stocked"

    def test_neutral_no_revenue_context(self):
        # Without revenue_yoy, falls through to neutral
        inv = [100, 102, 104, 106, 108]
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=None)
        assert flag == "neutral"


# ── enrich_shortage_signal ────────────────────────────────────────────────────

class TestEnrichShortageSignal:
    def test_all_empty_returns_zero_delta(self):
        result = enrich_shortage_signal(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert result.score_delta == 0
        assert result.gross_margin_trend == "unknown"
        assert result.capex_flag == "unknown"
        assert result.contract_liab_flag == "unknown"
        assert result.per_flag == "unknown"
        assert result.inventory_flag == "unknown"

    def test_expanding_margin_gives_boost(self):
        inc = _inc([100]*6, [80, 78, 75, 72, 68, 65])
        result = enrich_shortage_signal(inc, pd.DataFrame(), pd.DataFrame())
        assert result.score_delta > 0
        assert any("毛利擴張" in b for b in result.boosts)

    def test_contracting_margin_gives_warning_and_penalty(self):
        # 過水單：毛利下滑
        inc = _inc([100]*6, [65, 68, 72, 75, 78, 80])
        result = enrich_shortage_signal(inc, pd.DataFrame(), pd.DataFrame())
        assert result.score_delta < 0
        assert any("過水單" in w for w in result.warnings)

    def test_big_capex_gives_boost(self):
        cf = _cf([-100, -110, -120, -130, -200])
        result = enrich_shortage_signal(pd.DataFrame(), cf, pd.DataFrame())
        assert result.score_delta > 0
        assert any("買機台" in b for b in result.boosts)

    def test_strong_contract_liab_gives_boost_and_score(self):
        # Needs latest_monthly_revenue to qualify as "strong" (+1)
        bal = _bal([100, 110, 120, 130, 160])
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), bal,
            latest_monthly_revenue=70,
        )
        assert result.score_delta > 0
        assert any("合約負債" in b for b in result.boosts)

    def test_over_water_order_max_penalty(self):
        # 完美過水單：毛利下滑 + capex 縮減
        inc = _inc([200]*6, [130, 140, 155, 165, 175, 180])  # margin 35%→10%
        cf = _cf([-200, -180, -160, -140, -100])              # capex shrinking
        result = enrich_shortage_signal(inc, cf, pd.DataFrame())
        assert result.score_delta <= -2
        assert len(result.warnings) >= 2

    def test_full_quality_shortage_max_boost(self):
        # 真缺貨完美條件：毛利擴張 + 大買機台 + 合約負債暴增（有月營收門檻）
        inc = _inc([100]*6, [80, 78, 75, 72, 68, 65])
        cf = _cf([-100, -110, -120, -130, -200])
        bal = _bal([100, 110, 120, 130, 160])
        result = enrich_shortage_signal(
            inc, cf, bal,
            latest_monthly_revenue=70,   # 160 >= 70*2 → "strong"
        )
        assert result.score_delta >= 3
        assert len(result.boosts) >= 3
        assert len(result.warnings) == 0

    def test_cheap_per_gives_boost(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([8.0]),
        )
        assert result.score_delta > 0
        assert any("本益比" in b for b in result.boosts)

    def test_expensive_per_gives_penalty(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([35.0]),
        )
        assert result.score_delta < 0
        assert any("本益比偏高" in w for w in result.warnings)

    def test_sweet_spot_per_gives_boost(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([12.5]),
        )
        assert result.score_delta > 0
        assert any("甜蜜本益比" in b for b in result.boosts)

    def test_healthy_inventory_gives_boost(self):
        bal = _bal_inv([100, 105, 110, 120, 130])   # inv +30%
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), bal,
            revenue_yoy=25.0,
        )
        assert result.score_delta > 0
        assert any("健康備貨" in b for b in result.boosts)

    def test_channel_stuffing_gives_penalty(self):
        bal = _bal_inv([100, 110, 118, 122, 130])   # inv +30%
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), bal,
            revenue_yoy=-10.0,
        )
        assert result.score_delta < 0
        assert any("塞貨" in w for w in result.warnings)
