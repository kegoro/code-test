"""
DuckDB persistence layer.
Schema:
  prices(symbol, date, close, volume)
  institutional(symbol, date, name, buy, sell, net)
  margin(symbol, date, margin_balance, short_balance)
  shareholding(symbol, date, major_holder_ratio, shareholder_count)
  market_index(date, taiex_close, taiex_pct_change)
"""
import duckdb
import pandas as pd
from pathlib import Path
from loguru import logger
from config.settings import settings


def _conn() -> duckdb.DuckDBPyConnection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(settings.db_path))


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol  VARCHAR,
                date    DATE,
                close   DOUBLE,
                volume  DOUBLE DEFAULT 0,
                PRIMARY KEY (symbol, date)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS institutional (
                symbol  VARCHAR,
                date    DATE,
                name    VARCHAR,
                buy     BIGINT,
                sell    BIGINT,
                net     BIGINT,
                PRIMARY KEY (symbol, date, name)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS margin (
                symbol          VARCHAR,
                date            DATE,
                margin_balance  BIGINT,
                short_balance   BIGINT,
                PRIMARY KEY (symbol, date)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS shareholding (
                symbol              VARCHAR,
                date                DATE,
                major_holder_ratio  DOUBLE,
                shareholder_count   BIGINT,
                PRIMARY KEY (symbol, date)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS market_index (
                date              DATE PRIMARY KEY,
                taiex_close       DOUBLE,
                taiex_pct_change  DOUBLE
            )
        """)
        # Migrate existing prices table to add volume column if missing
        try:
            con.execute("ALTER TABLE prices ADD COLUMN IF NOT EXISTS volume DOUBLE DEFAULT 0")
        except Exception:
            pass
    logger.info("[store] DB initialized")


def upsert_prices(symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    cols = ["date", "close"] + (["volume"] if "volume" in df.columns else [])
    data = df[cols].assign(symbol=symbol)
    if "volume" not in data.columns:
        data["volume"] = 0.0
    with _conn() as con:
        con.register("_tmp_prices", data)
        con.execute(
            "INSERT OR REPLACE INTO prices SELECT symbol, date, close, volume FROM _tmp_prices"
        )


def upsert_institutional(symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    data = df[["date", "name", "buy", "sell", "net"]].assign(symbol=symbol)
    with _conn() as con:
        con.register("_tmp_inst", data)
        con.execute(
            "INSERT OR REPLACE INTO institutional "
            "SELECT symbol, date, name, buy, sell, net FROM _tmp_inst"
        )


def upsert_margin(symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    # fetch_margin already normalises to margin_balance / short_balance
    if "margin_balance" not in df.columns or "short_balance" not in df.columns:
        logger.warning(f"[store] {symbol} margin_balance/short_balance not found. cols={list(df.columns)}")
        return
    data = df[["date", "margin_balance", "short_balance"]].assign(symbol=symbol)
    with _conn() as con:
        con.register("_tmp_margin", data)
        con.execute(
            "INSERT OR REPLACE INTO margin "
            "SELECT symbol, date, margin_balance, short_balance FROM _tmp_margin"
        )


def upsert_shareholding(symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    data = df[["date", "major_holder_ratio", "shareholder_count"]].assign(symbol=symbol)
    with _conn() as con:
        con.register("_tmp_sh", data)
        con.execute(
            "INSERT OR REPLACE INTO shareholding "
            "SELECT symbol, date, major_holder_ratio, shareholder_count FROM _tmp_sh"
        )


def upsert_market_index(df: pd.DataFrame) -> None:
    if df.empty:
        return
    data = df[["date", "taiex_close", "taiex_pct_change"]]
    with _conn() as con:
        con.register("_tmp_mi", data)
        con.execute(
            "INSERT OR REPLACE INTO market_index "
            "SELECT date, taiex_close, taiex_pct_change FROM _tmp_mi"
        )


def read_prices(symbol: str) -> pd.DataFrame:
    with _conn() as con:
        return con.execute(
            "SELECT date, close, COALESCE(volume, 0) as volume FROM prices WHERE symbol=? ORDER BY date",
            [symbol],
        ).df()


def read_institutional(symbol: str, days: int = 30) -> pd.DataFrame:
    with _conn() as con:
        return con.execute(
            """SELECT date, name, net FROM institutional
               WHERE symbol=?
               ORDER BY date ASC LIMIT ?""",
            [symbol, days * 3],
        ).df()


def read_margin(symbol: str, days: int = 30) -> pd.DataFrame:
    with _conn() as con:
        return con.execute(
            """SELECT date, margin_balance, short_balance FROM margin
               WHERE symbol=?
               ORDER BY date ASC LIMIT ?""",
            [symbol, days],
        ).df()


def read_shareholding(symbol: str) -> pd.DataFrame:
    with _conn() as con:
        return con.execute(
            """SELECT date, major_holder_ratio, shareholder_count FROM shareholding
               WHERE symbol=? ORDER BY date ASC""",
            [symbol],
        ).df()


def read_market_index(days: int = 30) -> pd.DataFrame:
    with _conn() as con:
        return con.execute(
            """SELECT date, taiex_close, taiex_pct_change FROM market_index
               ORDER BY date ASC LIMIT ?""",
            [days],
        ).df()
