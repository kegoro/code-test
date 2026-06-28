# ============================================================
#  SMC Signal Monitor · 設定檔
#  config/settings.py
# ============================================================

import os
from dataclasses import dataclass, field
from typing import List

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID")

# ── Anthropic ─────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "YOUR_API_KEY")

# ── TradingView ───────────────────────────────────────────────
TV_USERNAME = os.getenv("TV_USERNAME", "")   # 可選：登入後才能存取 Premium 指標
TV_PASSWORD = os.getenv("TV_PASSWORD", "")

# TradingView 基礎 URL（台股用 TWSE prefix）
TV_BASE_URL = "https://www.tradingview.com/chart/?symbol=TWSE:{symbol}&interval={interval}"

# ── 監控設定 ───────────────────────────────────────────────────
@dataclass
class MonitorConfig:
    # 要持續掃描的股票清單（可透過 Telegram /watch 指令動態新增）
    watchlist: List[str] = field(default_factory=lambda: [
        "3481",  # 群創
        "2330",  # 台積電
        "2317",  # 鴻海
    ])

    # 掃描間隔（秒）— 預設 3 分鐘
    scan_interval_sec: int = 180

    # 每次掃描的時間框架（TV interval codes）
    timeframes: List[str] = field(default_factory=lambda: ["1", "5", "15"])

    # 訊號觸發冷卻時間：同一股同一訊號不重複通知（秒）
    signal_cooldown_sec: int = 600   # 10 分鐘

    # 截圖儲存天數（舊截圖自動清理）
    screenshot_retention_days: int = 3

    # 是否在推播時附上 HTML 分析報告
    send_html_report: bool = True

    # 推播服務（可同時多個）
    notify_telegram: bool = True
    notify_line:     bool = False   # 預留 LINE Notify 擴充

MONITOR = MonitorConfig()

# ── 偵測目標 SMC 訊號 ──────────────────────────────────────────
# Claude Vision 會在截圖中尋找這些標籤
TARGET_SIGNALS = [
    "BOS",          # Break of Structure
    "CHoCH",        # Change of Character
    "Weak Low",     # 脆弱低點（容易被清掃）
    "Weak High",    # 脆弱高點
    "EQL",          # Equal Lows / Equal Highs
    "FVG",          # Fair Value Gap（加分項）
    "OB",           # Order Block（加分項）
    "Liquidity",    # 流動性池（加分項）
]

# ── HTML 報告部署 ─────────────────────────────────────────────
# 選項 A: 上傳到 Telegraph（免費、匿名、無需帳號）
USE_TELEGRAPH = True
TELEGRAPH_ACCESS_TOKEN = os.getenv("TELEGRAPH_TOKEN", "")  # 第一次執行會自動建立

# 選項 B: 上傳到 Netlify（你已連接 Netlify MCP）
USE_NETLIFY = False
NETLIFY_SITE_ID = os.getenv("NETLIFY_SITE_ID", "")

# ── 日誌設定 ───────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_DIR   = "logs"
