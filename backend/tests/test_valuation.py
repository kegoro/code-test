"""估值判讀單元測試(純函式,不需網路)。"""
from backend.mops_fundamentals import YearMetrics
from backend import valuation as val

NAN = float("nan")


def _row(rev=None, gross=None, op=None, ocf=None, capex=None, label=None):
    return YearMetrics(year=2025, revenue=rev, gross=gross, op_income=op,
                       ocf=ocf, capex=capex, period_label=label)


def test_premium_reasons_high_margin_and_fcf():
    rows = [_row(rev=1000, gross=600, op=300, ocf=400, capex=-50)]  # GM60% OM30% 🟢 輕資產
    reasons = val.premium_reasons(rows)
    joined = " ".join(reasons)
    assert "高毛利率" in joined
    assert "營益率" in joined
    assert "FCF" in joined
    assert "輕資產" in joined


def test_premium_reasons_growth_and_expansion():
    rows = [
        _row(rev=100, gross=30),    # GM30%
        _row(rev=110, gross=38),    # GM35%
        _row(rev=130, gross=52),    # GM40% → 擴張 +10pt;年度 YoY=+18%(<20 不算高成長)
    ]
    joined = " ".join(val.premium_reasons(rows))
    assert "毛利率擴張" in joined


def test_premium_reasons_empty_when_mediocre():
    rows = [_row(rev=1000, gross=200, op=50, ocf=-10)]  # GM20% OM5% 🔴
    assert val.premium_reasons(rows) == []


def test_pe_verdict_band_expensive_cheap_fair():
    assert "偏貴" in val.pe_verdict_band(30, 18, 23, 29)
    assert "偏便宜" in val.pe_verdict_band(16, 18, 23, 29)
    assert "合理" in val.pe_verdict_band(23, 18, 23, 29)
    assert val.pe_verdict_band(NAN, 18, 23, 29) is None


def test_pe_verdict_growth_peg():
    assert "成長合理" in val.pe_verdict_growth(30, 45)      # PEG 0.67
    assert "略貴" in val.pe_verdict_growth(40, 25)          # PEG 1.6
    assert "嚴重偏貴" in val.pe_verdict_growth(60, 10)      # PEG 6
    assert "未成長" in val.pe_verdict_growth(30, 0)
    assert val.pe_verdict_growth(None, 20) is None


def test_format_reasons_always_has_qualitative_note():
    lines = val.format_reasons([])
    assert any("財報無明顯溢價因子" in ln for ln in lines)
    assert any("質化護城河" in ln for ln in lines)
