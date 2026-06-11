-- sim-trade Phase 1 schema (DuckDB). Time zone is always Asia/Taipei.
-- `ts` is the OPEN wall-clock time of each 1-minute bar.

CREATE TABLE IF NOT EXISTS kbars_tmf (
    ts             TIMESTAMP NOT NULL,
    epoch_s        BIGINT    NOT NULL,
    session_date   DATE      NOT NULL,
    session        VARCHAR   NOT NULL,   -- 'day' | 'night'
    open           DOUBLE    NOT NULL,
    high           DOUBLE    NOT NULL,
    low            DOUBLE    NOT NULL,
    close          DOUBLE    NOT NULL,
    volume         BIGINT    NOT NULL,   -- contracts (口)
    contract_month VARCHAR   NOT NULL,   -- source contract, e.g. 'TMFR1' / '202606'
    source         VARCHAR   NOT NULL DEFAULT 'shioaji',
    PRIMARY KEY (ts)
);

-- session_date = the date the session OPENED. The night session (15:00 -> next
-- day 05:00) is stored as one contiguous block under the opening evening's date
-- so a replay can play day+night of one date continuously.
--
-- WARNING — this differs from TAIFEX official attribution. Officially the night
-- session belongs to the NEXT trading day: e.g. the 2026-06-10 night session is
-- session_date = 2026-06-10 here, but TAIFEX daily data files it under
-- 2026-06-11. When backfilling from / reconciling against TAIFEX daily zip
-- volumes, convert with sessions.taifex_trading_day(); the two date definitions
-- are offset by exactly one trading day.

CREATE INDEX IF NOT EXISTS idx_kbars_tmf_session ON kbars_tmf (session_date, session, ts);

-- Flagged data gaps (holiday / missing minutes / halt) so replay can show a
-- hint instead of silently jumping.
CREATE TABLE IF NOT EXISTS sim_data_gaps (
    session_date DATE      NOT NULL,
    session      VARCHAR   NOT NULL,
    start_ts     TIMESTAMP NOT NULL,
    end_ts       TIMESTAMP NOT NULL,
    reason       VARCHAR,
    detected_at  TIMESTAMP DEFAULT now()
);

-- One replay practice session. `rewind_occurred` marks whether the user seeked
-- backward and re-watched bars they had already seen; performance stats use it
-- to separate clean sessions from rewound ones (honest-replay accounting).
CREATE TABLE IF NOT EXISTS sim_sessions (
    session_id      VARCHAR NOT NULL,
    session_date    DATE    NOT NULL,
    session         VARCHAR NOT NULL,
    resolution      INTEGER NOT NULL,
    speed           INTEGER NOT NULL,
    rewind_occurred BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT now(),
    PRIMARY KEY (session_id)
);
