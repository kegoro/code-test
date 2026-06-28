"""CDP 四線計算 + 訊號規則的單元測試。"""
from backend.cdp import compute_cdp, cdp_signal


def test_compute_cdp_levels():
    # 前日 高110 低90 收100 → CDP=100,振幅=20
    lv = compute_cdp(110, 90, 100)
    assert lv.cdp == 100
    assert lv.ah == 120   # CDP + 振幅
    assert lv.nh == 110   # 2×CDP − 低
    assert lv.nl == 90    # 2×CDP − 高
    assert lv.al == 80    # CDP − 振幅


def test_signal_open_at_ah_is_long():
    lv = compute_cdp(110, 90, 100)
    s = " ".join(cdp_signal(lv, open_p=121, last_p=121))
    assert "做多" in s and "AH" in s


def test_signal_open_at_al_is_short():
    lv = compute_cdp(110, 90, 100)
    s = " ".join(cdp_signal(lv, open_p=79, last_p=79))
    assert "放空" in s


def test_signal_open_crosses_nh_is_trend_long():
    lv = compute_cdp(110, 90, 100)
    s = " ".join(cdp_signal(lv, open_p=115, last_p=115))
    assert "穿越轉強 NH" in s


def test_signal_open_between_nh_nl_is_rangebound():
    lv = compute_cdp(110, 90, 100)
    s = " ".join(cdp_signal(lv, open_p=100, last_p=100))
    assert "盤整" in s


def test_signal_no_open_degrades_gracefully():
    lv = compute_cdp(110, 90, 100)
    s = " ".join(cdp_signal(lv, open_p=None, last_p=None))
    assert "尚無今日開盤價" in s


def test_signal_intraday_crosses_ah():
    lv = compute_cdp(110, 90, 100)
    # 開在區間內(100),盤中現價向上穿越 AH(120)
    s = " ".join(cdp_signal(lv, open_p=100, last_p=121))
    assert "穿越 AH" in s


def test_signal_intraday_near_nl_is_buy_point():
    lv = compute_cdp(110, 90, 100)
    # 開在區間內,現價貼近 NL(90)
    s = " ".join(cdp_signal(lv, open_p=100, last_p=90))
    assert "買進 / 回補" in s
