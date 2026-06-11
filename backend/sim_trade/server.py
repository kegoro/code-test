"""sim-trade replay server — FastAPI + WebSocket (localhost only).

DATA / REPLAY ONLY. No order routing. Run:

    python -m uvicorn backend.sim_trade.server:app --host 127.0.0.1 --port 8090 --reload

Protocol: see ``protocol.py`` and the Phase 1 design doc. One ``ReplayEngine`` is
created per connection on ``load``; a background task streams bars while playing.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import db as simdb
from . import protocol as P
from .replay import ReplayEngine

logger = logging.getLogger("sim_trade.server")

app = FastAPI(title="sim-trade replay", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    """Readiness probe: reports whether the sim DB has any sessions yet."""
    try:
        conn = simdb.connect(read_only=True)
    except Exception:  # noqa: BLE001 — DB not created yet
        return {"ok": True, "db_present": False, "sessions": 0}
    try:
        return {"ok": True, "db_present": True, "sessions": len(simdb.list_sessions(conn))}
    finally:
        conn.close()


@app.get("/sim/sessions")
async def sessions() -> list[dict]:
    """List available (session_date, session) blocks for the picker."""
    try:
        conn = simdb.connect(read_only=True)
    except Exception:  # noqa: BLE001
        return []
    try:
        return simdb.list_sessions(conn)
    finally:
        conn.close()


def _build_engine(msg: dict) -> ReplayEngine:
    """Load a session's bars and construct a ReplayEngine from a ``load`` command."""
    session_date = date.fromisoformat(msg["session_date"])
    session = msg.get("session", "day")
    conn = simdb.connect(read_only=True)
    try:
        bars = simdb.load_session_bars(conn, session_date, session)
    finally:
        conn.close()
    engine = ReplayEngine(bars, session, session_date)
    if "resolution" in msg:
        engine.resolution = int(msg["resolution"])
    if "speed" in msg:
        engine.speed = int(msg["speed"])
    return engine


@app.websocket("/sim/replay")
async def replay_ws(ws: WebSocket) -> None:
    """Replay control socket. See protocol.py for the command/event vocabulary."""
    await ws.accept()
    engine: ReplayEngine | None = None
    play_task: asyncio.Task | None = None
    send_lock = asyncio.Lock()

    async def send(events: list[dict]) -> None:
        async with send_lock:  # serialise frames across receive + play tasks
            for ev in events:
                await ws.send_json(ev)

    async def play_loop() -> None:
        try:
            while engine is not None and engine.playing:
                await send(engine.advance(1))
                if not engine.playing:
                    break
                await asyncio.sleep(1.0 / max(1, engine.speed))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("play loop stopped: %s", exc)

    def start_play() -> None:
        nonlocal play_task
        if play_task is None or play_task.done():
            play_task = asyncio.create_task(play_loop())

    try:
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("type")

            if cmd == P.CMD_LOAD:
                engine = _build_engine(msg)
                start_ts = msg.get("resume_ts") or msg.get("start_ts")
                await send(engine.load(start_ts=int(start_ts) if start_ts else None))
                continue

            if engine is None:
                await send([P.event(P.EV_ERROR, code="no_session", message="send `load` first")])
                continue

            if cmd == P.CMD_PLAY:
                await send(engine.play())
                if engine.playing:
                    start_play()
            elif cmd == P.CMD_PAUSE:
                await send(engine.pause())
            elif cmd == P.CMD_SPEED:
                await send(engine.set_speed(int(msg.get("value", 1))))
            elif cmd == P.CMD_STEP:
                await send(engine.step(int(msg.get("n", 1))))
            elif cmd == P.CMD_SEEK:
                await send(engine.seek(int(msg["to_ts"])))
            elif cmd == P.CMD_SET_RESOLUTION:
                await send(engine.set_resolution(int(msg.get("value", 1))))
            elif cmd == P.CMD_PING:
                await send(engine.ping())
            else:
                await send([P.event(P.EV_ERROR, code="bad_command", message=f"unknown: {cmd}")])
    except WebSocketDisconnect:
        logger.info("replay client disconnected")
    finally:
        if play_task is not None:
            play_task.cancel()
