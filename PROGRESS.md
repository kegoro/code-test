# Quant Terminal — PROGRESS

最後更新：2026-05-07

## 目前階段
**Phase 5 ✅ 完成：A 級掃描面板 UI + FinMind 真實資料接入**

### 本階段交付檔案
- `backend/scanner_models.py`
- `backend/volume_profile.py`
- `backend/scanner_a1.py`
- `backend/scanner_a2.py`
- `backend/no_trade_guard.py`
- `backend/scanner_scheduler.py`
- `backend/finmind_fetcher.py`
- `src/components/scanner/SetupScannerPanel.tsx`

### 下一步
- 升級 FinMind 付費 tier 或接入永豐 Shioaji 解鎖 M3 即時掃描

---

## Phase 5 Hotfix ✅ FinMind 真實資料源串接（2026-05-07）

- 新增 `backend/finmind_fetcher.py`：
  - `finmind_fetch_daily(symbol, lookback)` — `TaiwanStockPrice` daily OHLCV，欄位重命名 `max→high / min→low / Trading_Volume→volume`
  - `finmind_fetch_m3(symbol, day)` — `TaiwanStockKBar` 1 分鐘線 → `resample("3min")`
  - `parse_symbols_env()` — 讀 `SCANNER_SYMBOLS`，預設 6 檔（2382/2330/2449/2317/3231/6515）
  - 速率限制 0.5s/req、exponential backoff 最多 3 次
  - `FinMindPaywallError` typed exception：偵測 `"level is register"` / `"update your user level"` 回應，**不重試** 並標記全域 `_intraday_paywalled`
- `backend/main.py` lifespan：啟動時 `logger.info("scanner symbols: %s", symbols)`，從 `SCANNER_MARKET_HOURS_ONLY` env 讀取盤中限制旗標
- 驗證結果（盤後測試）：
  - 6 檔日線全部 200 OK 成功取回
  - `TaiwanStockKBar` 因免費 tier 受限回 400 → 自動切到 daily-fallback（用日線當 m3 輸入），不 crash、不重試
  - `GET /api/scanner/setups` 返回 `{"signals": []}`（合理：日線粒度 + 條件嚴格 + 標的多在 VA 之上脫離 sweep 區）
  - 真實 Volume Profile 範例：2330 POC=2055 / VAH=2200.5 / VAL=1925；2382 POC=321 / VAH=330.5 / VAL=303
- `.env.example` 補上 `SCANNER_SYMBOLS` 與 `SCANNER_MARKET_HOURS_ONLY`
- 註：要取得真正 3 分鐘線跑出 A1/A2 即時信號，需把 FinMind 帳號升級到付費 tier；其餘程式無需改動

---

## Phase 5 已完成（2026-05-07）

### 後端掃描引擎（純函數設計，可重用於回測）
- `backend/scanner_models.py`：`SetupSignal` / `ConditionCheck` / `VolumeProfileSnapshot` 等型別 + 常數（A1: 6/6 A 級、5/6 B 級；A2: 5/5 A 級、4/5 B 級；DEDUP_WINDOW=30 分鐘）
- `backend/volume_profile.py`：TPO 直方圖 + 70% Value Area + scipy.find_peaks 找 LVN/HVN（6 個 pytest）
- `backend/scanner_a1.py`：VA Edge Sweep Reversal — 6 條件（C1 Profile 形狀 / C2 wick 觸 VA / C3+C4 sweep+收回 / C5 POC 穩定 / C6 MSS / C7 Footprint 支撐）（3 個 pytest）
- `backend/scanner_a2.py`：LVN Acceptance Breakout — 2 前提 + 5 濾網（PRE1 ATR 收縮 / PRE2 LVN 鄰近；F1 量放大 / F2 Delta / F3 Stacked Imbalance / F4 收盤強度 / F5 回測不被吸收）+ R:R ≥ 1.5 過濾（3 個 pytest）
- `backend/no_trade_guard.py`：8 條硬性 NO TRADE（事件窗 / VA 中央死區 / HTF bias 不明 / 缺 body MSS / Footprint 衝突 / R:R 不足 / 連虧或日損 / spread 異常）

### 排程器與 SSE 推播
- `backend/scanner_scheduler.py`：`ScannerEngine` — asyncio loop，每 180 秒執行，盤後自動跳過；dedup 30 分鐘；SSE queue broadcast；信號過期主動推 `expire`
- `backend/main.py` 新增端點（不破壞 Phase 1-4 任何路由）：
  - `GET  /api/scanner/setups`           當前所有有效信號
  - `GET  /api/scanner/setups/{symbol}`  特定標的
  - `GET  /api/scanner/stream`           Server-Sent Events 即時流

### 前端整合
- `src/components/scanner/SetupScannerPanel.tsx`：右側面板新增掃描表格（代碼/Setup/評分/進場-停損/R:R），SSE 即時更新；A 級綠、B 級黃、失效灰刪除線
- `src/lib/telegram-message.ts`：新增 `scanner-a1` / `scanner-a2` payload kind + 訊息文案
- `src/components/dashboard/TelegramStatus.tsx`：補上對應標籤
- `src/app/api/telegram/route.ts`：未動（自動透過 `isTelegramPayload` 接受新 kind）
- `src/components/dashboard/DashboardClient.tsx`：在右側欄底部嵌入 `<SetupScannerPanel />`

### 測試 & 構建
- 後端：12 個 pytest 通過（volume_profile + scanner_a1 + scanner_a2）
- 前端：**94 / 94 vitest 通過**（原 29 + 既有其他測試）
- `npm run build` ✅ 通過 TypeScript 嚴格模式
- 後端啟動驗證：`/api/scanner/setups` 回傳 `{"signals": []}`（預設空 fetcher）

---

---

## Phase 1 ✅ 靜態 UI 三欄骨架（已驗收）
## Phase 2 ✅ 狀態機 + A/B/C 表單（已驗收）
## Phase 3 ✅ FinMind 真實 K 線 + 5 條 MA + Volume（已驗收）
## Phase 3 Hotfix ✅ Watchlist 真實報價 + Skeleton（已驗收）

---

## Phase 4 已完成

### Telegram API（規範 5、6）
- `src/app/api/telegram/route.ts`：POST 端點
  - 從 `process.env.TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 讀金鑰，未設定回 503 + 友善錯誤
  - 嚴格 payload 校驗（`isTelegramPayload`），只接受 `grade-a` / `entry-s4` / `raw` 三種結構化 kind
  - 訊息建構在伺服端執行（client 不能注入任意 HTML）
  - 呼叫 `https://api.telegram.org/bot{token}/sendMessage`，HTML parse mode
  - Telegram API 失敗回 502 + reason

### 訊息建構純函式（規範 8、9、10）
- `src/lib/telegram-message.ts`：
  - `escapeHtml()` — 處理 `& < >`
  - `buildTelegramMessage()` — 三種 kind 的格式化
  - `isTelegramPayload()` — 型別 narrow（拒絕未知 kind / 缺欄位）
  - 邊界處理：缺 quote 顯示 `—`、無限/NaN 防護

### 訊息文案
```
🚀 [A 級 Setup 觸發]
2382 廣達
目前報價：285.50 (+2.14%)
評分：A 級  A:8.6 / B:7.2 / C:9.1
動作：建議納入 S2 → S3 流程觀察
時間：2026-05-05 14:32
```
```
🟢 [進場觸發 — S4 Entry]
2449 京元電子
目前報價：142.00 (-1.04%)
評分：B 級
狀態：允許進場 (S4)
時間：2026-05-05 14:35
```

### 前端觸發（規範 5：邏輯解耦）
- `src/components/dashboard/useTelegramAlerts.ts`：
  - 兩個獨立 effect 監聽 `scoring.grade` 與 `tradeState`
  - 用 `useRef` 保存 prev 值 — **邊緣觸發**（只在跨界時送）
  - 首次掛載不發（`prevRef === null` 不送）→ 避免恢復狀態誤推
  - 失敗自動分流：503 → `disabled`、其他 → `error`
- `StateFlow` 改為**受控元件**（`current` + `onChange` props），讓 DashboardClient 持有 state，alert hook 才看得到變化
- `TelegramStatus` 標籤元件：右上角顯示最新事件 + 狀態 + 時間戳

### 單元測試
- `tests/telegram-message.test.ts` 11 個 it：
  - escapeHtml 邊界
  - isTelegramPayload 各種 happy / malformed
  - buildTelegramMessage 三種 kind + HTML 注入防護

**累計測試：3 suites / 29 tests passing**
- `tests/transitions.test.ts` 9
- `tests/evaluate.test.ts` 9
- `tests/telegram-message.test.ts` 11

### 部署準備
- `npm run build` ✅（4 個路由：`/`、`/_not-found`、`/api/kline/[symbol]`、`/api/quotes`、`/api/telegram`）
- `DEPLOY.md`：3 步驟（GitHub push → Vercel import → env vars）+ 驗收清單 + 常見問題

---

## 下一步（使用者操作）

1. **本地驗收 Phase 4**
   ```powershell
   $env:TELEGRAM_BOT_TOKEN="123456:ABC..."
   $env:TELEGRAM_CHAT_ID="你的chat_id"
   npm run dev
   ```
   - 勾滿 A 級 → 收到第一則訊息
   - 走 S0→S1→S2→S3，A 級+無旗標下點 S4 → 收到第二則訊息

2. **推到 GitHub + Vercel**：照 `DEPLOY.md` 的 3 步驟

3. **若要更精細的觸發規則**（例如：同一 symbol 60 秒內只發一次）
   現在是純跨界觸發，反覆勾選 → 取消 → 勾選會重發。如需 cooldown，後續可在 `useTelegramAlerts` 加 timestamp ref。

---

## 關鍵決策紀錄（追加 Phase 4）
| 決策 | 選擇 | 理由 |
|------|------|------|
| Token 暴露面 | 只在伺服端 route handler | 規範 6；client bundle 無 token |
| Payload 介面 | typed union (`grade-a` / `entry-s4` / `raw`) | 防 client 任意傳 HTML，且訊息文案集中在 server |
| 觸發方式 | edge-triggered + useRef prev | 規範 8 零歧義；不會因重 render 重發 |
| 首次掛載 | prev=null 時不發 | 規範 9 邊界；避免頁面重整誤推 |
| StateFlow | 改為受控元件 | 讓父層觀察狀態變化才能觸發 alert |
| HTML escape | 所有 user-controlled 字串都 escape | 防 Telegram parse_mode HTML 注入 |
| 失敗 UX | UI 不阻塞，標籤顯示 disabled / error | 沒設 token 時 app 仍能用 |

---

## 環境狀態
- Node：✅ 已安裝
- Tests：✅ 3 suites / 29 passing
- Build：✅ Next.js 16.2.4 Turbopack
- Routes：5 條（1 static + 1 not-found + 3 dynamic API）
- Secrets：仍走 `.env.local`（範例見 `.env.example`）

---

## 恢復方式
新對話說「繼續」或「Phase 5: backtest 開始」即可。
