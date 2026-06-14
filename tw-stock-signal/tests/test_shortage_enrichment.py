"""
Tests for strategy/shortage_enrichment.py (pure functions, no I/O).
"""
import pandas as pd
import pytest
from strategy.shortage_enrichment import (
    enrich_shortage_signal, EnrichmentResult,
    _gross_margin_analysis, _capex_analysis, _contract_liability_analysis,
    _pe_analysis, _inventory_analysis,
)


def _inc(revs: list[float], cogs: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=len(revs), freq="QE")
    return pd.DataFrame({"Revenue": revs, "CostOfGoodsSold": cogs}, index=idx)


def _cf(ppe_values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=len(ppe_values), freq="QE")
    return pd.DataFrame({"PropertyAndPlantAndEquipment": ppe_values}, index=idx)


def _bal(cl_values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=len(cl_values), freq="QE")
    return pd.DataFrame({"ContractLiabilities": cl_values}, index=idx)


def _bal_inv(inv_values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=len(inv_values), freq="QE")
    return pd.DataFrame({"Inventories": inv_values}, index=idx)


def _per(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"PER": values}, index=idx)


# ── _gross_margin_analysis ────────────────────────────────────────────────────

class TestGrossMarginAnalysis:
    def test_returns_unknown_on_empty(self):
        gm, trend = _gross_margin_analysis(pd.DataFrame())
        assert gm is None
        assert trend == "unknown"

    def test_expanding_margin_trend_up(self):
        revs = [100, 100, 100, 100, 100, 100]
        cogs = [80, 78, 75, 72, 68, 65]
        _, trend = _gross_margin_analysis(_inc(revs, cogs))
        assert trend == "up"

    def test_contracting_margin_trend_down(self):
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

    def test_strong_with_absolute_threshold(self):
        cl = [100, 110, 120, 130, 160]  # +60% YoY, 160 >= 70*2=140
        _, flag = _contract_liability_analysis(_bal(cl), latest_monthly_revenue=70)
        assert flag == "strong"

    def test_high_yoy_without_absolute_is_growing(self):
        cl = [100, 110, 120, 130, 160]
        _, flag = _contract_liability_analysis(_bal(cl))
        assert flag == "growing"

    def test_growing(self):
        cl = [100, 104, 108, 112, 115]  # ~+15%
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

    def test_cheap(self):
        _, flag = _pe_analysis(_per([8.5]))
        assert flag == "cheap"

    def test_sweet_spot_lower(self):
        _, flag = _pe_analysis(_per([10.0]))
        assert flag == "sweet_spot"

    def test_sweet_spot_upper(self):
        _, flag = _pe_analysis(_per([15.0]))
        assert flag == "sweet_spot"

    def test_fair(self):
        _, flag = _pe_analysis(_per([20.0]))
        assert flag == "fair"

    def test_fair_covers_monopoly_premium(self):
        # 壟斷龍頭 25-30x 屬 fair
        _, flag = _pe_analysis(_per([28.0]))
        assert flag == "fair"

    def test_expensive(self):
        per_val, flag = _pe_analysis(_per([40.0]))
        assert flag == "expensive"
        assert per_val == pytest.approx(40.0)

    def test_negative_returns_unknown(self):
        per_val, flag = _pe_analysis(_per([-5.0]))
        assert per_val is None
        assert flag == "unknown"

    def test_extreme_value_returns_unknown(self):
        per_val, flag = _pe_analysis(_per([500.0]))
        assert per_val is None
        assert flag == "unknown"

    def test_uses_latest_value(self):
        _, flag = _pe_analysis(_per([50.0, 30.0, 12.0]))
        assert flag == "sweet_spot"


# ── _inventory_analysis ───────────────────────────────────────────────────────

class TestInventoryAnalysis:
    def test_returns_unknown_on_empty(self):
        inv_yoy, flag = _inventory_analysis(pd.DataFrame())
        assert inv_yoy is None
        assert flag == "unknown"

    def test_insufficient_data(self):
        _, flag = _inventory_analysis(_bal_inv([100, 110]), revenue_yoy=20.0)
        assert flag == "unknown"

    def test_healthy_buildup(self):
        inv = [100, 105, 110, 120, 130]  # +30% YoY, rev up +25%
        inv_yoy, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=25.0)
        assert flag == "healthy_buildup"
        assert inv_yoy == pytest.approx(30.0)

    def test_tight_supply(self):
        inv = [100, 95, 90, 88, 80]  # inv down, rev up
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=20.0)
        assert flag == "tight_supply"

    def test_channel_stuffing(self):
        inv = [100, 110, 118, 122, 130]  # inv +30%, rev down -10%
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=-10.0)
        assert flag == "channel_stuffing"

    def test_over_stocked(self):
        inv = [100, 120, 140, 155, 170]  # inv +70%, rev up
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=20.0)
        assert flag == "over_stocked"

    def test_neutral_without_revenue(self):
        inv = [100, 102, 104, 106, 108]
        _, flag = _inventory_analysis(_bal_inv(inv), revenue_yoy=None)
        assert flag == "neutral"


# ── enrich_shortage_signal ────────────────────────────────────────────────────

class TestEnrichShortageSignal:
    def test_all_empty_returns_no_badges(self):
        result = enrich_shortage_signal(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert result.badges == []
        assert result.gross_margin_trend == "unknown"
        assert result.capex_flag == "unknown"
        assert result.contract_liab_flag == "unknown"
        assert result.per_flag == "unknown"
        assert result.inventory_flag == "unknown"

    def test_margin_up_badge(self):
        inc = _inc([100]*6, [80, 78, 75, 72, 68, 65])
        result = enrich_shortage_signal(inc, pd.DataFrame(), pd.DataFrame())
        assert any("毛利↑" in b for b in result.badges)

    def test_margin_down_badge_includes_warning(self):
        inc = _inc([100]*6, [65, 68, 72, 75, 78, 80])
        result = enrich_shortage_signal(inc, pd.DataFrame(), pd.DataFrame())
        assert any("過水單" in b for b in result.badges)

    def test_expanding_capex_badge(self):
        cf = _cf([-100, -110, -120, -130, -200])
        result = enrich_shortage_signal(pd.DataFrame(), cf, pd.DataFrame())
        assert any("買機台" in b for b in result.badges)

    def test_shrinking_capex_badge(self):
        cf = _cf([-200, -180, -160, -140, -100])
        result = enrich_shortage_signal(pd.DataFrame(), cf, pd.DataFrame())
        assert any("Capex 縮" in b for b in result.badges)

    def test_stable_capex_no_badge(self):
        cf = _cf([-100, -102, -98, -101, -100])
        result = enrich_shortage_signal(pd.DataFrame(), cf, pd.DataFrame())
        assert not any("Capex" in b for b in result.badges)

    def test_contract_liab_badge(self):
        bal = _bal([100, 110, 120, 130, 160])
        result = enrich_shortage_signal(pd.DataFrame(), pd.DataFrame(), bal,
                                        latest_monthly_revenue=70)
        assert any("合約負債" in b for b in result.badges)

    def test_per_cheap_badge(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([8.0]),
        )
        assert any("偏低" in b for b in result.badges)

    def test_per_sweet_spot_badge(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([12.5]),
        )
        assert any("甜蜜點" in b for b in result.badges)

    def test_per_expensive_badge_no_penalty(self):
        # 高本益比只顯示資訊，不影響任何評分
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([40.0]),
        )
        assert any("偏高" in b for b in result.badges)

    def test_per_fair_monopoly_has_badge(self):
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            per_df=_per([28.0]),
        )
        assert any("本益比" in b for b in result.badges)

    def test_healthy_inventory_badge(self):
        bal = _bal_inv([100, 105, 110, 120, 130])
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), bal,
            revenue_yoy=25.0,
        )
        assert any("健康備貨" in b for b in result.badges)

    def test_channel_stuffing_badge(self):
        bal = _bal_inv([100, 110, 118, 122, 130])
        result = enrich_shortage_signal(
            pd.DataFrame(), pd.DataFrame(), bal,
            revenue_yoy=-10.0,
        )
        assert any("塞貨地雷" in b for b in result.badges)

    def test_full_data_all_five_badges(self):
        inc = _inc([100]*6, [80, 78, 75, 72, 68, 65])  # margin up
        cf  = _cf([-100, -110, -120, -130, -200])        # capex expanding
        bal = _bal([100, 110, 120, 130, 160])             # contract liab
        result = enrich_shortage_signal(
            inc, cf, bal,
            per_df=_per([12.0]),
            revenue_yoy=25.0,
            latest_monthly_revenue=70,
        )
        # 至少有毛利、買機台、合約負債、本益比四個 badge
        assert len(result.badges) >= 4
