"""Tests for the cursor-based replay engine, incl. the zero-lookahead invariant."""
from __future__ import annotations

from datetime import date

from backend.sim_trade import protocol as P
from backend.sim_trade.replay import ReplayEngine

from .conftest import build_base_bars

SD = date(2026, 6, 10)


def _types(events):
    return [e["type"] for e in events]


def make_engine(n=10, **kw):
    return ReplayEngine(build_base_bars(SD, "day", n, **kw), "day", SD)


def test_load_starts_empty_snapshot():
    eng = make_engine(10)
    evs = eng.load()
    assert _types(evs) == [P.EV_LOADED, P.EV_SNAPSHOT, P.EV_STATE]
    assert evs[0]["bar_count"] == 10
    assert evs[1]["bars"] == []          # cursor = -1 reveals nothing
    assert eng.cursor == -1


def test_advance_reveals_one_bar_at_a_time():
    eng = make_engine(10)
    eng.load()
    eng.advance(3)
    assert eng.cursor == 2
    assert len(eng.revealed) == 3


def test_zero_lookahead_no_event_exceeds_cursor():
    eng = make_engine(20)
    eng.load()
    for _ in range(20):
        for ev in eng.advance(1):
            if ev["type"] == P.EV_BAR:
                cursor_ts = eng._bars[eng.cursor].epoch_s
                # an emitted bar's bucket-open time can never be after the cursor
                assert ev["bar"]["time"] <= cursor_ts
        # revealed slice never extends past the cursor
        assert all(b.epoch_s <= eng._bars[eng.cursor].epoch_s for b in eng.revealed)


def test_set_resolution_reaggregates_only_revealed():
    eng = make_engine(10)
    eng.load()
    eng.advance(3)                       # reveal 3 one-minute bars
    snap, state = eng.set_resolution(5)
    assert snap["type"] == P.EV_SNAPSHOT
    assert snap["resolution"] == "5"
    assert len(snap["bars"]) == 1        # 3 bars -> one forming 5-min bucket
    assert snap["bars"][0]["closed"] is False


def test_seek_backward_flags_rewind():
    eng = make_engine(10)
    eng.load()
    eng.advance(8)
    target = eng._bars[2].epoch_s
    eng.seek(target)
    assert eng.cursor == 2
    assert eng.rewind_occurred is True


def test_seek_forward_does_not_flag_rewind():
    eng = make_engine(10)
    eng.load()
    eng.seek(eng._bars[5].epoch_s)
    assert eng.cursor == 5
    assert eng.rewind_occurred is False


def test_gap_event_emitted_when_crossing_hole():
    eng = make_engine(10, skip=(4,))     # minute 4 missing -> gap between bar3 and bar5
    eng.load()
    seen_gap = False
    for _ in range(12):
        for ev in eng.advance(1):
            if ev["type"] == P.EV_GAP:
                seen_gap = True
    assert seen_gap


def test_contract_switch_event_on_roll():
    eng = make_engine(10, roll_at=5)
    eng.load()
    switches = []
    for _ in range(12):
        for ev in eng.advance(1):
            if ev["type"] == P.EV_CONTRACT_SWITCH:
                switches.append(ev)
    assert len(switches) == 1
    assert switches[0]["from_month"] == "TMFR1"
    assert switches[0]["to_month"] == "TMFR2"


def test_advance_past_end_emits_end_and_stops():
    eng = make_engine(3)
    eng.load()
    eng.play()
    saw_end = False
    for _ in range(10):
        for ev in eng.advance(1):
            if ev["type"] == P.EV_END:
                saw_end = True
    assert saw_end
    assert eng.playing is False
    assert eng.at_end


def test_bad_resolution_and_speed_return_error():
    eng = make_engine(3)
    eng.load()
    assert eng.set_resolution(7)[0]["type"] == P.EV_ERROR
    assert eng.set_speed(2)[0]["type"] == P.EV_ERROR
