"""Daily signal card — Andrew framework (Layer A + B).

Run after 09:15 (after the 30-min opening range closes):

    python -m backend.daily_signal          # print card
    python -m backend.daily_signal --log    # print + append to data/paper_log.csv
    python -m backend.daily_signal --tg     # print + send to Telegram

What it does:
  1. Refresh Layer A (download latest US macro data)
  2. Fetch today's TXF 1-min bars via Shioaji
  3. Compute ORH / ORL from first OR_WINDOW_MIN bars
  4. Output the trade setup card
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from backend.env_guard import require
require("pandas", "shioaji")

import pandas as pd

from backend.layer_a import fetch_and_save as refresh_layer_a, DATA_PATH as LAYER_A_PATH
from backend.layer_b import OR_START, SESSION_START, SESSION_END
from backend.shioaji_fetcher import _get_api, _kbars_to_df, _empty_ohlcv
from backend.fetch_txf_csv import _resolve_contract

logger = logging.getLogger("daily_signal")

# ── parameters (must match backtest) ─────────────────────────────────────────
OR_WINDOW_MIN  = 30
STOP_PTS       = 30.0
REWARD_MULT    = 2.0
BIAS_THRESHOLD = 1
TZ             = "Asia/Taipei"
PAPER_LOG      = Path(__file__).resolve().parent.parent / "data" / "paper_log.csv"


# ── fetch today's TXF bars ────────────────────────────────────────────────────

def _fetch_today_bars() -> pd.DataFrame:
    api = _get_api()
    contract = _resolve_contract(api)
    today = date.today().isoformat()
    try:
        kbars = api.kbars(contract, start=today, end=today)
        df = _kbars_to_df(kbars)
    except Exception as exc:
        logger.error("fetch today bars failed: %s", exc)
        return _empty_ohlcv()

    if df.empty:
        return df

    # tz-aware
    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        idx = idx.tz_localize(TZ)
    else:
        idx = idx.tz_convert(TZ)
    # close-label → open-label
    idx = idx - pd.Timedelta(minutes=1)
    df.index = idx

    # day session only
    t = df.index.time
    df = df[(t >= SESSION_START) & (t <= SESSION_END)]
    return df.sort_index()


CSV_1M = Path(__file__).resolve().parent.parent / "data" / "txf_1min.csv"


# ── compute ORH / ORL ─────────────────────────────────────────────────────────

def _compute_or(df: pd.DataFrame) -> tuple[float, float, float]:
    """Return (ORH, ORL, last_price). Raises if not enough bars yet."""
    if df.empty:
        raise RuntimeError("No bars — is the market open?")
    first_bar = df.index[0]
    or_cutoff = first_bar + pd.Timedelta(minutes=OR_WINDOW_MIN)
    or_bars = df[df.index <= or_cutoff]
    if len(or_bars) < 5:
        raise RuntimeError(
            f"Only {len(or_bars)} bars in OR window — run after 09:15"
        )
    orh = float(or_bars["high"].max())
    orl = float(or_bars["low"].min())
    last = float(df["close"].iloc[-1])
    return orh, orl, last


def _compute_or_from_csv() -> tuple[float, float, float]:
    """Fallback: read most recent day from txf_1min.csv and compute OR."""
    if not CSV_1M.exists():
        raise RuntimeError("data/txf_1min.csv not found — run python -m backend.fetch_txf_csv first")
    df = pd.read_csv(CSV_1M, parse_dates=["datetime"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(TZ)
    last_date = df["datetime"].dt.date.max()
    day_df = df[df["datetime"].dt.date == last_date].copy()
    if day_df.empty:
        raise RuntimeError(f"No bars in CSV for {last_date}")
    first_bar = day_df["datetime"].iloc[0]
    or_cutoff = first_bar + pd.Timedelta(minutes=OR_WINDOW_MIN)
    or_bars = day_df[day_df["datetime"] <= or_cutoff]
    if len(or_bars) < 5:
        raise RuntimeError(f"Not enough bars in OR window for {last_date}")
    orh = float(or_bars["high"].max())
    orl = float(or_bars["low"].min())
    last = float(day_df["close"].iloc[-1])
    logger.warning("⚠ 使用 CSV 最後一天 (%s) 的 OR，非今日即時資料", last_date)
    return orh, orl, last


# ── layer A bias ──────────────────────────────────────────────────────────────

def _get_bias() -> tuple[int, int, int, int]:
    """Return (bias_a, a1, a2, a3) from most recent Layer A row."""
    if not LAYER_A_PATH.exists():
        raise RuntimeError("layer_a_daily.csv not found. Run: python -m backend.layer_a")
    df = pd.read_csv(LAYER_A_PATH, parse_dates=["date"], index_col="date")
    if df.empty:
        raise RuntimeError("layer_a_daily.csv is empty")
    row = df.iloc[-1]
    return int(row["bias_a"]), int(row.get("a1", 0)), int(row.get("a2", 0)), int(row.get("a3", 0))


# ── format card ───────────────────────────────────────────────────────────────

def _make_card(
    orh: float, orl: float, last: float,
    bias_a: int, a1: int, a2: int, a3: int,
) -> str:
    or_range = orh - orl
    target_pts = max(or_range * REWARD_MULT, STOP_PTS * REWARD_MULT)

    if bias_a >= BIAS_THRESHOLD:
        direction = "LONG ▲"
        entry   = orh
        stop    = round(orh - STOP_PTS, 0)
        target  = round(orh + target_pts, 0)
        trigger = f"突破 {orh:.0f} → 進場"
    elif bias_a <= -BIAS_THRESHOLD:
        direction = "SHORT ▼"
        entry   = orl
        stop    = round(orl + STOP_PTS, 0)
        target  = round(orl - target_pts, 0)
        trigger = f"跌破 {orl:.0f} → 進場"
    else:
        direction = "SKIP — 觀望"
        entry = stop = target = 0.0
        trigger = f"bias_a={bias_a}，不符合門檻"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    bias_bar = "▓" * (abs(bias_a)) + "░" * (3 - abs(bias_a))
    bias_sign = "+" if bias_a > 0 else ""

    lines = [
        f"━━━ 台指期日盤訊號卡 {now} ━━━",
        f"",
        f"Layer A  bias = {bias_sign}{bias_a}  [{bias_bar}]",
        f"  A1 美債殖利率：{'↓ 偏多' if a1 > 0 else '↑ 偏空'}",
        f"  A2 美元指數  ：{'↓ 偏多' if a2 > 0 else '↑ 偏空'}",
        f"  A3 三大指數  ：{'同步收紅' if a3 > 0 else '同步收綠' if a3 < 0 else '分歧'}",
        f"",
        f"Layer B  OR({OR_WINDOW_MIN}min)",
        f"  ORH = {orh:.0f}   ORL = {orl:.0f}",
        f"  OR 範圍 = {or_range:.0f} pts   現價 = {last:.0f}",
        f"",
        f"方向   {direction}",
        f"觸發   {trigger}",
    ]

    if bias_a >= BIAS_THRESHOLD or bias_a <= -BIAS_THRESHOLD:
        lines += [
            f"進場   {entry:.0f}",
            f"停損   {stop:.0f}  （-{STOP_PTS:.0f} pts）",
            f"目標   {target:.0f}  （+{target_pts:.0f} pts，{REWARD_MULT}× OR）",
            f"時間   最晚 13:30 出場",
        ]

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ── paper log ─────────────────────────────────────────────────────────────────

def _append_log(card_data: dict) -> None:
    df_new = pd.DataFrame([card_data])
    if PAPER_LOG.exists():
        existing = pd.read_csv(PAPER_LOG)
        out = pd.concat([existing, df_new], ignore_index=True)
    else:
        out = df_new
    PAPER_LOG.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(PAPER_LOG, index=False)
    logger.info("logged → %s", PAPER_LOG)


# ── telegram send ─────────────────────────────────────────────────────────────

async def _send_telegram(text: str) -> None:
    # 統一走 SMC bot（與排程 _job_morning_report 同一支），fallback 舊變數
    token   = os.getenv("SMC_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("SMC_TELEGRAM_CHAT_ID")  or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("SMC_TELEGRAM_BOT_TOKEN / SMC_TELEGRAM_CHAT_ID not set")
        return
    try:
        import httpx
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: httpx.post(url, data={"chat_id": chat_id, "text": text}, timeout=10),
        )
        if resp.status_code == 200:
            logger.info("Telegram sent OK")
        else:
            logger.error("Telegram error %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Generate today's TXF signal card")
    parser.add_argument("--log",     action="store_true", help="Append to paper_log.csv")
    parser.add_argument("--tg",      action="store_true", help="Send card to Telegram")
    parser.add_argument("--refresh", action="store_true", help="Re-download Layer A data")
    parser.add_argument("--orh",     type=float, default=None, help="Manual ORH (skip API)")
    parser.add_argument("--orl",     type=float, default=None, help="Manual ORL (skip API)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s | %(message)s")

    # 1) optionally refresh Layer A
    if args.refresh:
        logger.info("Refreshing Layer A macro data…")
        refresh_layer_a()

    # 2) bias
    try:
        bias_a, a1, a2, a3 = _get_bias()
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    # 3) today's OR levels  (manual > live API > CSV fallback)
    if args.orh is not None and args.orl is not None:
        orh, orl, last = float(args.orh), float(args.orl), float(args.orl)
    else:
        try:
            df = _fetch_today_bars()
            orh, orl, last = _compute_or(df)
        except RuntimeError:
            # kbars returns empty during live session → try yesterday's CSV
            try:
                orh, orl, last = _compute_or_from_csv()
            except RuntimeError as e:
                logger.error("%s", e)
                logger.error(
                    "提示：Shioaji kbars 盤中不提供即時 K 線。\n"
                    "請從看盤軟體讀出 ORH/ORL 後手動輸入：\n"
                    "  python -m backend.daily_signal --orh <ORH> --orl <ORL> --log"
                )
                return 1

    # 4) card
    card = _make_card(orh, orl, last, bias_a, a1, a2, a3)
    print(card)

    # 5) log
    if args.log:
        or_range = orh - orl
        direction = "long" if bias_a >= BIAS_THRESHOLD else ("short" if bias_a <= -BIAS_THRESHOLD else "skip")
        _append_log({
            "date":      date.today().isoformat(),
            "bias_a":    bias_a,
            "orh":       orh,
            "orl":       orl,
            "or_range":  round(or_range, 1),
            "direction": direction,
            "entry":     orh if direction == "long" else (orl if direction == "short" else ""),
            "stop":      round(orh - STOP_PTS, 0) if direction == "long" else (round(orl + STOP_PTS, 0) if direction == "short" else ""),
            "target":    round(orh + max(or_range * REWARD_MULT, STOP_PTS * REWARD_MULT), 0) if direction == "long"
                         else (round(orl - max(or_range * REWARD_MULT, STOP_PTS * REWARD_MULT), 0) if direction == "short" else ""),
            "actual_exit": "",   # fill in manually after close
            "actual_pnl":  "",   # fill in manually after close
            "notes":       "",
        })

    # 6) Telegram
    if args.tg:
        asyncio.run(_send_telegram(card))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
