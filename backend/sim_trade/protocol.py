"""Replay WebSocket protocol constants + helpers (see Phase 1 design doc).

Speed is expressed in **base bars per second** (1-minute bars). The UI labels it
as ``N 根/秒`` (N bars/sec), NOT as a multiplier, because "1 根/秒" is already
60x real time and calling it "1x" misleads.
"""
from __future__ import annotations

from typing import Any

# ── control commands (client -> server) ────────────────────────────────────────
CMD_LOAD = "load"
CMD_PLAY = "play"
CMD_PAUSE = "pause"
CMD_SPEED = "speed"
CMD_STEP = "step"
CMD_SEEK = "seek"
CMD_SET_RESOLUTION = "set_resolution"
CMD_PING = "ping"

# ── events (server -> client) ──────────────────────────────────────────────────
EV_LOADED = "loaded"
EV_SNAPSHOT = "snapshot"
EV_BAR = "bar"
EV_STATE = "state"
EV_GAP = "gap"
EV_CONTRACT_SWITCH = "contract_switch"
EV_END = "end"
EV_ERROR = "error"
EV_PONG = "pong"

RESOLUTIONS: tuple[int, ...] = (1, 3, 5, 15, 30, 60)
SPEEDS: tuple[int, ...] = (1, 5, 30)  # base bars per second


def speed_label(bars_per_sec: int) -> str:
    """UI label for a speed setting — bars/sec, never a multiplier."""
    return f"{bars_per_sec} 根/秒"


def event(type_: str, **kw: Any) -> dict:
    """Build a server->client event dict."""
    return {"type": type_, **kw}
