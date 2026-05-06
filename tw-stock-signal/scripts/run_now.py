"""
Manual pipeline trigger for testing and ad-hoc runs.

Usage:
  python scripts/run_now.py                      # fetch + analyze (no Telegram)
  python scripts/run_now.py --notify             # fetch + analyze + send Telegram
  python scripts/run_now.py --step fetch         # only fetch raw data
  python scripts/run_now.py --step analyze       # only compute signals
  python scripts/run_now.py --step notify        # only send Telegram (uses existing signals file)
  python scripts/run_now.py --step heartbeat     # run the 07:55 readiness check
  python scripts/run_now.py --step saturday      # manual Saturday volume top 10
  python scripts/run_now.py --step sunday        # manual Sunday foreign buy top 10
"""
import sys
import asyncio
import argparse
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from config.settings import settings

logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")


async def _run(step: str, notify: bool) -> None:
    from scheduler.daily_job import (
        fetch_job, analyze_job, notify_job, heartbeat_job, run_pipeline,
    )
    from scheduler.calendar import is_trading_day, prev_trading_date

    trading_date = prev_trading_date().isoformat()
    logger.info(f"Manual run | step={step} | notify={notify} | trading_date={trading_date}")
    logger.info(f"Is today a trading day: {is_trading_day()}")

    match step:
        case "fetch":
            await fetch_job()
        case "analyze":
            await analyze_job()
        case "notify":
            await notify_job()
        case "heartbeat":
            await heartbeat_job()
        case "saturday":
            from scheduler.daily_job import saturday_volume_job
            await saturday_volume_job()
        case "sunday":
            from scheduler.daily_job import sunday_foreign_job
            await sunday_foreign_job()
        case "all":
            await run_pipeline(notify=notify)
        case _:
            logger.error(f"Unknown step: {step}")
            sys.exit(1)

    logger.info("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual trigger for the tw-stock-signal pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        choices=["all", "fetch", "analyze", "notify", "heartbeat", "saturday", "sunday"],
        default="all",
        help="Which stage to run (default: all)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send Telegram notification (only applies when --step=all)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.step, args.notify))


if __name__ == "__main__":
    main()
