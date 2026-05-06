"""
Telegram notification layer.
"""
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from loguru import logger
from config.settings import settings
from strategy.signal import Signal
from .report import (
    build_telegram_messages,
    build_detail_message,
    build_live_card,
    build_error_alert,
    build_heartbeat_warning,
)


def _bot() -> Bot:
    return Bot(token=settings.telegram_bot_token)


async def send_daily_report(signals: list[Signal]) -> None:
    """Send the full daily report: summary messages + per-stock detail cards."""
    bot = _bot()
    chat_id = settings.telegram_chat_id

    for msg in build_telegram_messages(signals):
        await _send(bot, chat_id, msg)
        await asyncio.sleep(0.8)

    buy_signals = [s for s in signals if s.recommendation == "積極佈局"]
    for sig in buy_signals:
        await _send(bot, chat_id, build_detail_message(sig))
        await asyncio.sleep(0.5)

    logger.info(f"[telegram] Report sent: {len(signals)} signals, {len(buy_signals)} detail cards")


async def send_live_signal(signal) -> None:
    """
    Send a single per-stock card immediately after analysis.
    Only called when signal.hard_pass is True.
    Never raises — a failure must not block the analysis loop.
    """
    try:
        await _send(_bot(), settings.telegram_chat_id, build_live_card(signal))
    except Exception as exc:
        logger.error(f"[telegram] send_live_signal {signal.symbol} failed: {exc}")


async def send_error_alert(job_name: str, error: str) -> None:
    """Send a job failure alert. Never raises — failure to alert should not crash the caller."""
    try:
        await _send(_bot(), settings.telegram_chat_id, build_error_alert(job_name, error))
    except Exception as exc:
        logger.error(f"[telegram] send_error_alert itself failed: {exc}")


async def send_heartbeat_warning(detail: str) -> None:
    """Send a 07:55 data-not-ready warning."""
    try:
        await _send(_bot(), settings.telegram_chat_id, build_heartbeat_warning(detail))
    except Exception as exc:
        logger.error(f"[telegram] send_heartbeat_warning failed: {exc}")


async def send_html_message(text: str) -> None:
    """Send a single HTML-formatted message."""
    await _send(_bot(), settings.telegram_chat_id, text)


async def send_text(text: str) -> None:
    """Generic plaintext message (no HTML)."""
    try:
        bot = _bot()
        await bot.send_message(chat_id=settings.telegram_chat_id, text=text)
    except Exception as exc:
        logger.error(f"[telegram] send_text failed: {exc}")


async def _send(bot: Bot, chat_id: str, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        logger.debug(f"[telegram] Sent {len(text)} chars")
    except TelegramError as exc:
        logger.error(f"[telegram] Send failed: {exc}")
