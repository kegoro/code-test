# SMC Signal Monitor

自動化 TradingView SMC 訊號偵測 + Telegram 推播系統

```
截圖 → Claude Vision 分析 → HTML 報告 → Telegram 推播
```

---

## 功能一覽

| 功能 | 說明 |
|------|------|
| 📸 自動截圖 | Playwright 無頭瀏覽器，自動開啟 TradingView 截圖 |
| 🔍 Claude 分析 | Vision API 識別 BOS / CHoCH / Weak Low / EQL / FVG / OB |
| 📊 HTML 報告 | 精美深色主題，含關鍵價位、訊號列表、操作建議 |
| 📲 Telegram Bot | 接收指令 + 主動推播截圖 + 報告 |
| ⏱ 定時掃描 | 背景每 3 分鐘自動掃描 watchlist |
| ❄️ 冷卻防重複 | 同訊號 10 分鐘內不重複推播 |
| 🕐 多時間框架 | /mtf 指令同時分析 1m / 5m / 15m |

---

## 安裝步驟

### 1. 環境準備
```bash
# 建議 Python 3.11+
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium     # 安裝無頭瀏覽器
```

### 2. 設定 API 金鑰
```bash
cp .env.example .env
# 編輯 .env，填入以下三項（必填）：
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHAT_ID
#   ANTHROPIC_API_KEY
```

### 3. 建立 Telegram Bot
1. 打開 Telegram → 搜尋 `@BotFather`
2. 發送 `/newbot`，取得 `BOT_TOKEN`
3. 搜尋 `@userinfobot`，取得你的 `CHAT_ID`

### 4. 啟動
```bash
python main.py
```

---

## Telegram 指令

| 指令 | 功能 |
|------|------|
| `/scan 3481` | 立即分析 3481（1m） |
| `/scan AAPL 5` | 分析 AAPL 5 分鐘圖 |
| `/mtf 2330` | 多時間框架分析（1m/5m/15m） |
| `/watch 3481` | 加入自動監控 |
| `/unwatch 3481` | 移出監控 |
| `/list` | 查看監控清單 |
| `/status` | 系統狀態 |

---

## 專案結構

```
smc_monitor/
├── main.py                    # 主程式入口
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py            # 全域設定
├── core/
│   ├── screenshotter.py       # TradingView 截圖（Playwright）
│   └── analyzer.py            # Claude Vision 分析
├── notifier/
│   └── telegram_bot.py        # Bot 指令 + 推播 + 定時掃描
├── web/
│   └── report_generator.py    # HTML 報告生成
├── screenshots/               # 截圖儲存（自動清理）
└── logs/                      # 執行日誌
```

---

## 偵測的 SMC 訊號

- **BOS** — Break of Structure（結構突破）
- **CHoCH** — Change of Character（結構轉換）
- **Weak Low / Weak High** — 脆弱低/高點（流動性目標）
- **EQL** — Equal Lows / Highs（等高低點）
- **FVG** — Fair Value Gap（公平價值缺口）
- **OB** — Order Block（機構訂單區）

---

## 重要限制

> TradingView 的 SMC 標籤是 Pine Script 前端渲染，**無法直接爬取數值**。
> 本系統透過「截圖 + Claude Vision」來識別訊號，準確度取決於：
> 1. 截圖解析度（1440×900 已優化）
> 2. 圖表上的 SMC Indicator 是否已啟用
> 3. Claude 的圖像識別能力

**最佳方案（進階）：** 在 TradingView Premium 設定 Pine Script Alert → Webhook，
直接將訊號 POST 到你的伺服器，完全繞過截圖識別，精準度 100%。

---

## 擴充路線圖

- [ ] TradingView Webhook 接收端（精準版）
- [ ] LINE Notify 並行推播
- [ ] 訊號歷史記錄（SQLite）
- [ ] 勝率統計 Dashboard
- [ ] Discord 支援
