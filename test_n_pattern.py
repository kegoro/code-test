"""N 字 setup 單元測試（合成資料）。

涵蓋情境（對應 LESSONS.md §2.7 N 字戰法 4 階段）：
  1. 黃金路徑：Beat 1 +2.5% → 拉回 OB → 未突破 H1 → 觸發
  2. 第一拍 < 2% → 不觸發
  3. L1 沒落在 OB → 不觸發
  4. OB 失守（L1 之後跌破 OB bottom）→ 不觸發
  5. close 已突破 H1（Beat 3 已過）→ 不觸發
  6. 時段不對（open_drive / close_drive）→ 不觸發

執行：
  pytest test_n_pattern.py -v
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backend.smc_analyst.context import AnalysisContext, Frame, LiquidityMap
from backend.smc_analyst.setups.n_pattern import NPattern


_TZ = ZoneInfo("Asia/Taipei")


def _make_m1_bars(opens: list[float], highs: list[float],
                  lows: list[float], closes: list[float],
                  date: str = "2026-05-16") -> pd.DataFrame:
    """從 9:00 開始每 1 分鐘一根 K 構造 1m bars。"""
    n = len(opens)
    idx = pd.date_range(f"{date} 09:00", periods=n, freq="1min", tz=_TZ)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1000] * n},
        index=idx,
    )


def _make_ctx(
    *,
    m1_bars: pd.DataFrame,
    active_obs: list[dict],
    session_phase: str = "trend_morning",
    htf_bias: str = "bullish",
    now_tw: datetime | None = None,
) -> AnalysisContext:
    """組一個 minimal AnalysisContext 給 NPattern.evaluate 用。"""
    if now_tw is None:
        now_tw = m1_bars.index[-1].to_pydatetime()
    htf_struct = {
        "structure": htf_bias,
        "swing_points": {"swing_highs": [], "swing_lows": []},
        "last_bos": None, "last_choch": None,
    }
    empty_struct = {
        "structure": "ranging",
        "swing_points": {"swing_highs": [], "swing_lows": []},
        "last_bos": None, "last_choch": None,
    }
    htf = Frame("1D", pd.DataFrame(), 5, htf_struct)
    mtf = Frame("60m", pd.DataFrame(), 5, empty_struct)
    ltf = Frame("1m", m1_bars, 10, empty_struct)
    return AnalysisContext(
        symbol="TEST",
        now_tw=now_tw,
        session_phase=session_phase,  # type: ignore[arg-type]
        htf=htf, mtf=mtf, ltf=ltf,
        liquidity=LiquidityMap(),
        pd_zones=None,
        mtf_levels={},
        equal_pivots={"equal_highs": [], "equal_lows": []},
        strong_weak={},
        active_obs=active_obs,
        active_fvgs=[],
        trendlines=None,
        atr_ltf=0.5,
    )


def _bullish_ob(bottom: float, top: float, formed_bar: int = 5) -> dict:
    return {"bias": "bullish", "bottom": bottom, "top": top, "formed_bar": formed_bar}


# ── 黃金路徑 ───────────────────────────────────────────────────────────────────

def _golden_path_bars() -> pd.DataFrame:
    """合成 30 根 1m：100→103 (+3%) → 平緩回測到 100.7（落在 OB 100.4-101.0）→ 反彈到 102。"""
    rows = []
    # 第 1 段（idx 0-9）：100 → 103 線性上漲
    for i in range(10):
        c = 100.0 + 0.3 * (i + 1)              # close 100.3 → 103.0
        rows.append((c - 0.1, c + 0.05, c - 0.15, c))   # open/high/low/close
    # 第 2 段（idx 10-19）：103 → 100.7 平緩回測（每根 -0.23）
    for i in range(10):
        c = 103.0 - 0.23 * (i + 1)             # 102.77 → 100.7
        rows.append((c + 0.05, c + 0.1, c - 0.05, c))
    # 第 3 段（idx 20-29）：100.7 → 102 反彈（每根 +0.13），未突破 H1=103
    for i in range(10):
        c = 100.7 + 0.13 * (i + 1)             # 100.83 → 102.0
        rows.append((c - 0.1, c + 0.1, c - 0.15, c))

    opens, highs, lows, closes = zip(*rows)
    return _make_m1_bars(list(opens), list(highs), list(lows), list(closes))


def test_n_pattern_golden_path_triggers():
    """Beat1 +3% → 平緩回測到 OB → 當前未突破 H1 → 應觸發。"""
    m1 = _golden_path_bars()
    obs = [_bullish_ob(bottom=100.4, top=101.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs)

    match = NPattern().evaluate(ctx)
    assert match is not None, "黃金路徑應觸發"
    assert match.direction == "long"
    assert match.entry == 101.0    # OB top
    assert match.stop == 100.4     # OB bottom
    assert match.target > 102.0    # H1 應該 > 102
    assert match.score > 0
    assert any("Beat 1" in r for r in match.reasoning)
    assert any("Beat 2" in r for r in match.reasoning)


# ── 否定情境 ───────────────────────────────────────────────────────────────────

def test_first_beat_too_weak():
    """第一拍只漲 +1% → 未達 2% 門檻，不觸發。"""
    n = 30
    # 開盤 100，最高 101（+1%），其他都在 100-101 之間
    opens = [100.0] * n
    highs = [101.0] + [100.5] * (n - 1)
    lows = [99.5] * n
    closes = [100.0] * n
    m1 = _make_m1_bars(opens, highs, lows, closes)
    obs = [_bullish_ob(99.0, 99.8)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs)
    assert NPattern().evaluate(ctx) is None


def test_l1_not_in_ob():
    """L1 沒落在任何 OB 內 → 不觸發。"""
    opens = [100.0] * 30
    highs = [103.0 if i == 5 else 101.0 for i in range(30)]
    lows = [99.5 if i != 15 else 100.5 for i in range(30)]  # L1=100.5
    closes = [100.5] * 30
    m1 = _make_m1_bars(opens, highs, lows, closes)
    # OB 區間 95-96，L1=100.5 不在此區間
    obs = [_bullish_ob(95.0, 96.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs)
    assert NPattern().evaluate(ctx) is None


def test_ob_broken_after_l1():
    """L1 落在 OB 內，但之後又跌破 OB bottom → DB 失守，不觸發。"""
    # H1=103 在 idx 5，L1=100.5 在 idx 15（落在 OB 100.4-101），但 idx 20 跌到 99
    opens = [100.0] * 30
    highs = [103.0 if i == 5 else 101.0 for i in range(30)]
    lows = [99.5] * 30
    lows[15] = 100.5      # L1 in OB
    lows[20] = 99.0       # 之後破 OB bottom (100.4)
    closes = [100.5] * 30
    m1 = _make_m1_bars(opens, highs, lows, closes)
    obs = [_bullish_ob(100.4, 101.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs)
    assert NPattern().evaluate(ctx) is None


def test_already_broke_h1():
    """當前 close 已突破 H1（N 字 Beat 3 已成立）→ 進場太晚，不觸發。"""
    opens = [100.0] * 30
    highs = [103.0 if i == 5 else 101.0 for i in range(30)]
    highs[-1] = 104.0
    lows = [99.5 if i != 15 else 100.5 for i in range(30)]
    closes = [100.5] * 30
    closes[-1] = 103.5    # 已突破 H1=103
    m1 = _make_m1_bars(opens, highs, lows, closes)
    obs = [_bullish_ob(100.4, 101.0)]
    ctx = _make_ctx(m1_bars=m1, active_obs=obs)
    assert NPattern().evaluate(ctx) is None


def test_session_phase_outside_window():
    """session_phase = open_drive 或 close_drive → 不觸發。"""
    opens = [100.0] * 30
    highs = [103.0 if i == 5 else 101.0 for i in range(30)]
    lows = [99.5 if i != 15 else 100.5 for i in range(30)]
    closes = [100.5] * 30
    m1 = _make_m1_bars(opens, highs, lows, closes)
    obs = [_bullish_ob(100.4, 101.0)]

    for phase in ("open_drive", "close_drive", "closed"):
        ctx = _make_ctx(m1_bars=m1, active_obs=obs, session_phase=phase)
        assert NPattern().evaluate(ctx) is None, f"phase={phase} 不應觸發"


def test_htf_bearish_halves_score():
    """HTF bearish 時，counter-trend 分數減半。"""
    m1 = _golden_path_bars()
    obs = [_bullish_ob(100.4, 101.0)]

    bull_match = NPattern().evaluate(_make_ctx(m1_bars=m1, active_obs=obs, htf_bias="bullish"))
    bear_match = NPattern().evaluate(_make_ctx(m1_bars=m1, active_obs=obs, htf_bias="bearish"))

    assert bull_match is not None
    assert bear_match is not None
    # bull/bear raw_score 不同（bull 多 1 分 HTF bonus），故驗證減半邏輯本身：
    assert bull_match.score == bull_match.raw_score, "HTF aligned 不應減半"
    assert bear_match.score == bear_match.raw_score // 2, "HTF 反向應減半"
    assert bull_match.htf_aligned is True
    assert bear_match.htf_aligned is False


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
