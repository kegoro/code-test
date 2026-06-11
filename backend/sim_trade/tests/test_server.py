"""WebSocket integration test for the replay server (seeded temp DB)."""
from __future__ import annotations

from datetime import date

import pytest

from backend.sim_trade import db as simdb

from .conftest import build_kbar_rows

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _seed(tmp_db):
    conn = simdb.connect(tmp_db)
    simdb.init_schema(conn)
    simdb.upsert_kbars(conn, build_kbar_rows(date(2026, 6, 10), "day", 10))
    conn.close()


def test_ws_load_step_resolution_seek_ping(tmp_db):
    _seed(tmp_db)
    from backend.sim_trade.server import app  # imported after SIM_TRADE_DB is set

    client = fastapi_testclient.TestClient(app)
    with client.websocket_connect("/sim/replay") as ws:
        ws.send_json({"type": "load", "session_date": "2026-06-10", "session": "day", "resolution": 1})
        loaded = ws.receive_json()
        assert loaded["type"] == "loaded"
        assert loaded["bar_count"] == 10
        assert ws.receive_json()["type"] == "snapshot"
        assert ws.receive_json()["type"] == "state"

        # step 5 base bars -> five closed 1-minute bar events
        ws.send_json({"type": "step", "n": 5})
        for _ in range(5):
            bar = ws.receive_json()
            assert bar["type"] == "bar"
            assert bar["bar"]["closed"] is True

        # switch resolution -> fresh snapshot + state
        ws.send_json({"type": "set_resolution", "value": 5})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["resolution"] == "5"
        assert ws.receive_json()["type"] == "state"

        # seek backward from bar 4 to the first bar -> rewound flag
        ws.send_json({"type": "seek", "to_ts": loaded["first_ts"]})
        assert ws.receive_json()["type"] == "snapshot"
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["rewound"] is True

        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ws_rejects_commands_before_load(tmp_db):
    _seed(tmp_db)
    from backend.sim_trade.server import app

    client = fastapi_testclient.TestClient(app)
    with client.websocket_connect("/sim/replay") as ws:
        ws.send_json({"type": "play"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "no_session"
