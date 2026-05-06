from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(..., description="Telegram Bot API token")
    telegram_chat_id: str = Field(..., description="Target chat/channel ID")

    finmind_api_token: str = Field(default="", description="FinMind API token (free tier OK)")

    db_path: Path = Field(default=Path("data/tw_stock.duckdb"))
    log_level: str = Field(default="INFO")

    finmind_base_url: str = "https://api.finmindtrade.com/api/v4/data"
    finmind_rate_limit_delay: float = 0.5  # seconds between requests

    playwright_headless: bool = True
    playwright_timeout_ms: int = 30_000

    lookback_days: int = 420  # ~280 trading days → enough buffer above MA240+slope(260)
    ma_period: int = 240
    watchlist_path: Path = Path("config/watchlist.yaml")  # used only in watchlist mode

    # Full-market scan settings
    full_market_scan: bool = False     # True = scan all ~1700 stocks; False = use watchlist
    universe_concurrency: int = 3      # Max concurrent symbols (free tier: keep ≤ 5)
    min_price_filter: float = 10.0     # Exclude stocks with latest close < this value

    # Scheduler settings
    timezone: str = "Asia/Taipei"
    fetch_retry_attempts: int = 3
    fetch_retry_delay_secs: int = 300   # 5 minutes between retries

    # Data directory (all output files)
    data_dir: Path = Path("data")


settings = Settings()
