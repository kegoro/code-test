# Quant Terminal — PROGRESS

最後更新：2026-05-05

## 目前階段
**Phase 4：Telegram 推播 + Vercel 部署準備（程式完成，等使用者推到 GitHub + 設環境變數）**

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
