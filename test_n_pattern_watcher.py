"""N 字 watcher 單元測試（first_beat + db_approach）。"""
from __future__ import annotations

import pandas as pd

from backend.n_pattern_watcher import evaluate_db_approach, evaluate_first_beat
from test_n_pattern import _bullish_ob, _make_ctx, _make_m1_bars


# ── first_beat ─────────────────────────────────────────────────────────────────

def _first_beat_bars(rise_pct: float = 3.0, total_bars: int = 9) -> pd.DataFrame:
    """合成「正在拉升」的 m1 bars — H1 在最後一根。

    目的：H1_idx 出現在末端 → first_beat 應觸發。
    """
    rows = []
    open_px = 100.0
    target = open_px * (1 + rise_pct / 100)
    for i in range(total_bars):
        c = open_px + (target - open_px) * (i + 1) / total_bars
        rows.append((c - 0.05, c + 0.05, c - 0.1, c))
    opens, highs, lows, closes = zip(*rows)
    return _make_m1_bars(list(opens), list(highs), list(lows), list(closes))


def test_first_beat_triggers_on_fresh_h1():
    m1 = _first_beat_bars(rise_pct=3.0, total_bars=9)
    ctx = _make_ctx(m1_bars=m1, active_obs=[], session_phase="open_drive")
    alert = evaluate_first_beat(ctx)
    assert alert is not None
    assert alert.symbol == "TEST"
    assert 2.0 <= alert.h1_pct <= 5.0
    assert "第一拍" in alert.to_telegram_text()


def test_first_beat_skipped_if_pct_below_min():
    m1 = _first_beat_bars(rise_pct=1.0, total_bars=9)
    ctx = _make_ctx(m1_bars=m1, active_obs=[], session_phase="open_drive")
    assert evaluate_first_beat(ctx) is None


def test_first_beat_skipped_if_pct_above_max():
    m1 = _first_beat_bars(rise_pct=7.0, total_bars=9)
    ctx = _make_ctx(m1_bars=m1, active_obs=[], session_phase="open_drive")
    # 7% > 5%（FIRST_BEAT_MAX_PCT）→ 視為過熱不再算第一拍候選
    assert evaluate_first_beat(ctx) is None


def test_first_beat_skipped_if_h1_too_old():
    """H1 在很早的位置（後續又跌了），表示已回測，不算「剛形成的第一拍」。"""
    # 30 根 m1 → 10 根 m3。H1 在 idx 3，最後 7 根都低於 H1
    rows = []
    for i in range(10):
        c = 100.0 + 0.3 * (i + 1)  # 100.3 → 103.0
        rows.append((c - 0.1, c + 0.05, c - 0.15, c))
    for i in range(20):
        rows.append((101.0, 101.5, 100.5, 101.0))
    opens, highs, lows, closes = zip(*rows)
    m1 = _make_m1_bars(list(opens), list(highs), list(lows), list(closes))
    ctx = _make_ctx(m1_bars=m1, active_obs=[], session_phase="trend_morning")
    assert evaluate_first_beat(ctx) is None


def test_first_beat_skipped_if_session_closed():
    m1 = _first_beat_bars(rise_pct=3.0)
    for phase in ("closed", "lunch", "trend_afternoon", "close_drive"):
        ctx = _make_ctx(m1_bars=m1, active_obs=[], session_phase=phase)
        assert evaluate_first_beat(ctx) is None, f"phase={phase} 不該觸發"


# ── db_approach ────────────────────────────────────────────────────────────────

def test_db_approach_triggers_when_close_in_ob():
    m1 = _make_m1_bars([100, 101], [101, 101], [99, 100.5], [100.7, 100.7])
    obs = [_bullish_ob(bottom=100.4, top=101.0, formed_bar=10)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase="trend_morning")
    alert = evaluate_db_approach(ctx)
    assert alert is not None
    assert alert.ob_bottom == 100.4
    assert alert.ob_top == 101.0
    assert alert.distance_to_top < 0  # close 100.7 在 OB 內
    assert "進場區" in alert.to_telegram_text()


def test_db_approach_triggers_when_close_just_above_ob():
    """close 略高於 OB top，但在 ATR×0.3 容忍範圍內 → 仍觸發（即將回測）。"""
    # ATR 設 0.5，proximity 0.3 → tol = 0.15
    m1 = _make_m1_bars([100, 101], [101, 101], [99, 101.0], [101.1, 101.1])
    obs = [_bullish_ob(bottom=100.4, top=101.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase="trend_morning")
    # _make_ctx 預設 atr_ltf=0.5 → tol = 0.15，close 101.1 在 OB top + tol = 101.15 內
    alert = evaluate_db_approach(ctx)
    assert alert is not None
    assert alert.distance_to_top > 0


def test_db_approach_skipped_when_close_far_above():
    m1 = _make_m1_bars([100, 105], [101, 105], [99, 104], [105, 105])
    obs = [_bullish_ob(bottom=100.4, top=101.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase="trend_morning")
    # close 105 遠高於 OB top + tol → 不觸發
    assert evaluate_db_approach(ctx) is None


def test_db_approach_skipped_for_bearish_ob():
    """N 字戰法只看 bullish OB（DB），bearish OB 不算。"""
    m1 = _make_m1_bars([100, 101], [101, 101], [99, 100.5], [100.7, 100.7])
    obs = [{"bias": "bearish", "bottom": 100.4, "top": 101.0, "formed_bar": 10}]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase="trend_morning")
    assert evaluate_db_approach(ctx) is None


def test_db_approach_skipped_if_session_closed():
    m1 = _make_m1_bars([100, 101], [101, 101], [99, 100.5], [100.7, 100.7])
    obs = [_bullish_ob(bottom=100.4, top=101.0)]
    for phase in ("closed", "open_drive", "close_drive"):
        ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase=phase)
        assert evaluate_db_approach(ctx) is None, f"phase={phase} 不該觸發"


# ── alert state dedup（整合驗證）──────────────────────────────────────────────

def test_alert_state_dedup_round_trip(tmp_path):
    """should_push → mark_pushed → should_push（同 key 在窗內應返 False）。"""
    from backend import alert_state

    p = tmp_path / "state.json"
    key = "first_beat:2330:2026-05-16"

    assert alert_state.should_push(key, path=p) is True
    alert_state.mark_pushed(key, path=p)
    assert alert_state.should_push(key, within_minutes=60, path=p) is False
    # 不同 key 不互相影響
    assert alert_state.should_push("first_beat:2317:2026-05-16", path=p) is True


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
