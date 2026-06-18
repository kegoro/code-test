"""美股 SEC XBRL 抓取的單元測試(差分引擎,不需網路)。"""
from datetime import date

from backend.us_fundamentals import (
    _annual_duration,
    _duration_quarterly,
    _eps_series,
    _instant_series,
)


def _node(rows):
    """組一個假 companyfacts 概念 node:rows = [(start, end, val, form)]。"""
    return {"units": {"USD": [
        {"start": s, "end": e, "val": v, "form": f} for s, e, v, f in rows
    ]}}


def _eps_node(rows):
    """EPS 概念 node(單位 USD/shares):rows = [(start, end, val, form)]。"""
    return {"units": {"USD/shares": [
        {"start": s, "end": e, "val": v, "form": f} for s, e, v, f in rows
    ]}}


def test_quarterly_from_ytd_cumulative():
    # 一條 YTD 累計線(10-Q)+ 全年(10-K),應還原成四個單季增量。
    node = _node([
        ("2025-01-01", "2025-03-31", 100e6, "10-Q"),  # 累計Q1=100
        ("2025-01-01", "2025-06-30", 250e6, "10-Q"),  # 累計H1=250 → Q2=150
        ("2025-01-01", "2025-09-30", 420e6, "10-Q"),  # 累計9M=420 → Q3=170
        ("2025-01-01", "2025-12-31", 600e6, "10-K"),  # 全年=600 → Q4=180
    ])
    q = _duration_quarterly(node)
    assert q[date(2025, 3, 31)] == 100  # 百萬美元
    assert q[date(2025, 6, 30)] == 150
    assert q[date(2025, 9, 30)] == 170
    assert q[date(2025, 12, 31)] == 180


def test_quarterly_accepts_single_quarter_filings():
    # 公司同時報「單季」筆(start 各季初):應直接視為單季值。
    node = _node([
        ("2025-04-01", "2025-06-30", 150e6, "10-Q"),  # 單季Q2
        ("2025-07-01", "2025-09-30", 170e6, "10-Q"),  # 單季Q3
    ])
    q = _duration_quarterly(node)
    assert q[date(2025, 6, 30)] == 150
    assert q[date(2025, 9, 30)] == 170


def test_later_filing_overrides_restatement():
    # 同期(start,end)後申報覆蓋先申報(重述)。
    node = _node([
        ("2025-01-01", "2025-03-31", 100e6, "10-Q"),
        ("2025-01-01", "2025-03-31", 110e6, "10-K"),  # 後到的重述值
    ])
    q = _duration_quarterly(node)
    assert q[date(2025, 3, 31)] == 110


def test_half_year_gap_not_misread_as_quarter():
    # 缺 Q2 時,Q1→Q3 跨度約半年,不可誤當單季。
    node = _node([
        ("2025-01-01", "2025-03-31", 100e6, "10-Q"),
        ("2025-01-01", "2025-09-30", 420e6, "10-Q"),  # 缺 H1,跨度 183 天
    ])
    q = _duration_quarterly(node)
    assert date(2025, 3, 31) in q
    assert date(2025, 9, 30) not in q  # 半年跨度被排除


def test_non_10kq_forms_ignored():
    # 只採 10-K / 10-Q;8-K 等不計入。
    node = _node([
        ("2025-01-01", "2025-03-31", 100e6, "8-K"),
    ])
    assert _duration_quarterly(node) == {}


def test_instant_series_uses_period_end():
    # 時點概念(資產負債表)以期末日為 key。
    node = _node([
        ("2025-01-01", "2025-03-31", 3000e6, "10-Q"),
        ("2025-04-01", "2025-06-30", 3200e6, "10-Q"),
    ])
    s = _instant_series(node)
    assert s[date(2025, 3, 31)] == 3000
    assert s[date(2025, 6, 30)] == 3200


def test_annual_duration_keeps_full_year_only():
    node = _node([
        ("2025-01-01", "2025-03-31", 100e6, "10-Q"),   # 一季,排除
        ("2024-01-01", "2024-12-31", 600e6, "10-K"),   # 全年,保留
    ])
    a = _annual_duration(node)
    assert a == {date(2024, 12, 31): 600}


def test_eps_series_picks_single_quarter_no_scaling():
    # EPS 不可乘/除 1e6;只挑單季(80~100 天)的筆,YTD/全年累計排除。
    node = _eps_node([
        ("2025-04-01", "2025-06-30", 1.50, "10-Q"),   # 單季Q2,保留
        ("2025-01-01", "2025-06-30", 2.80, "10-Q"),   # 累計H1,排除(181 天)
    ])
    eps = _eps_series(node, quarterly=True)
    assert eps == {date(2025, 6, 30): 1.50}


def test_eps_series_annual():
    node = _eps_node([
        ("2025-04-01", "2025-06-30", 1.50, "10-Q"),    # 單季,排除
        ("2024-01-01", "2024-12-31", 6.20, "10-K"),    # 全年,保留
    ])
    eps = _eps_series(node, quarterly=False)
    assert eps == {date(2024, 12, 31): 6.20}
