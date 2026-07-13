"""CDP 四線計算 + 訊號規則的單元測試。"""
import pytest

from backend.cdp import compute_cdp, cdp_signal, levels_payload


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


# ── 畫線 payload(圖表用) ───────────────────────────────────────────────────

def test_levels_payload_shape_and_prices():
    # 沿用 110/90/100 → AH120 NH110 CDP100 NL90 AL80
    lv = compute_cdp(110, 90, 100)
    payload = levels_payload(lv)
    assert [p["key"] for p in payload] == ["AH", "NH", "CDP", "NL", "AL"]
    by_key = {p["key"]: p for p in payload}
    assert by_key["AH"]["price"] == 120
    assert by_key["NH"]["price"] == 110
    assert by_key["CDP"]["price"] == 100
    assert by_key["NL"]["price"] == 90
    assert by_key["AL"]["price"] == 80
    # 每條線都要有 label + color
    for p in payload:
        assert p["label"] and p["color"].startswith("#")
    # 突破/轉弱同紅、轉強/跌破同綠(對齊前端色票)
    assert by_key["AH"]["color"] == by_key["NL"]["color"]
    assert by_key["NH"]["color"] == by_key["AL"]["color"]
    assert by_key["CDP"]["color"] != by_key["AH"]["color"]


def test_cdp_endpoint_returns_ok_levels(monkeypatch):
    """/datafeed/cdp 回傳結構化 JSON(mock 取數,避開 shioaji/yfinance)。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import backend.cdp as cdp_mod

    async def fake_fetch(symbol):
        return compute_cdp(110, 90, 100, prev_date="2026-07-11"), None, None

    monkeypatch.setattr(cdp_mod, "fetch_levels", fake_fetch)

    from tv_chart.backend.main import app

    client = TestClient(app)
    resp = client.get("/datafeed/cdp", params={"symbol": "2330"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["s"] == "ok"
    assert data["symbol"] == "2330"
    assert data["prev_date"] == "2026-07-11"
    assert [lv["key"] for lv in data["levels"]] == ["AH", "NH", "CDP", "NL", "AL"]


def test_cdp_endpoint_reports_error(monkeypatch):
    """取數失敗時回 s=error,不丟 500。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import backend.cdp as cdp_mod

    async def fake_fetch(symbol):
        raise cdp_mod.CDPDataError("查無日線")

    monkeypatch.setattr(cdp_mod, "fetch_levels", fake_fetch)

    from tv_chart.backend.main import app

    client = TestClient(app)
    resp = client.get("/datafeed/cdp", params={"symbol": "9999"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["s"] == "error"
    assert "查無日線" in data["errmsg"]
