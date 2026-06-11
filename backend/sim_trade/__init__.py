"""sim-trade — 微台指(TMF)模擬交易平台 (Phase 1: data layer + replay engine).

DATA / REPLAY ONLY. This package never routes real orders; it only consumes
Shioaji quote/kbar APIs. Any future live-trading capability MUST live in a
separate module marked ``# LIVE TRADING`` with its own max-loss guard.

Distinct from ``backend.sim_book`` (the Telegram paper-trading book) — different
store, different purpose. Do not merge.
"""
