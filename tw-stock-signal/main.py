"""
Entry points:
  python main.py              → run full pipeline once (fetch + analyze + notify)
  python main.py --daemon     → scheduler + Telegram bot (runs forever)
  python main.py --no-notify  → run pipeline without sending Telegram
  python main.py --bot-only   → interactive Telegram bot only (no scheduler)
"""
import asyncio
import sys
from loguru import logger
from config.settings import settings

logger.remove()
logger.add(sys.stderr, level=settings.log_level, colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
logger.add(f"{settings.data_dir}/logs/app_{{time:YYYY-MM-DD}}.log",
           rotation="1 day", retention="7 days", level="DEBUG")


def main() -> None:
    if "--daemon" in sys.argv:
        # run_polling() owns the event loop; APScheduler starts inside post_init
        from notifier.bot_handler import build_application
        app = build_application(with_scheduler=True)
        logger.info("Starting daemon + Telegram bot (Ctrl-C to stop)")
        app.run_polling(drop_pending_updates=False)

    elif "--bot-only" in sys.argv:
        from notifier.bot_handler import build_application
        app = build_application(with_scheduler=False)
        logger.info("Starting Telegram bot only (Ctrl-C to stop)")
        app.run_polling(drop_pending_updates=False)

    else:
        from scheduler.daily_job import run_pipeline
        notify = "--no-notify" not in sys.argv
        asyncio.run(run_pipeline(notify=notify))


if __name__ == "__main__":
    main()
