# Deploy to Vercel — 3 步驟上線指南

> 適用：Quant Terminal v0.4.0（含 FinMind 數據源 + Telegram 推播）

---

## 步驟 1：推送到 GitHub

在專案根目錄（`C:\Users\sfudally\Desktop\code test`）執行：

```powershell
# 第一次需要先 init（已 init 過可跳過）
git init -b main

# 過濾這個工作目錄裡的 sibling clone 與大檔，只追蹤本專案
# .gitignore 已預先寫好（node_modules、.next、.env.local 都會被忽略）

git add .gitignore .env.example DEPLOY.md PROGRESS.md README.md `
        package.json package-lock.json tsconfig.json `
        next.config.ts postcss.config.mjs tailwind.config.ts vitest.config.ts `
        src tests

git commit -m "feat: initial trading terminal with FinMind + Telegram"

# 在 GitHub 建立空 repo（例如 quant-terminal），然後：
git remote add origin https://github.com/<你的帳號>/quant-terminal.git
git push -u origin main
```

> ⚠️ **重要**：絕對不要 `git add .`，因為工作目錄底下還有 `TradingAgents/`、`KLineChart/`、`FinMind/` 等別人的 clone。請只 add 本專案實際需要的檔案/資料夾（如上）。

---

## 步驟 2：在 Vercel 匯入專案

1. 登入 [vercel.com](https://vercel.com)，點 **Add New → Project**。
2. 選你剛 push 的 GitHub repo（`quant-terminal`）。
3. **Framework Preset** 自動偵測為 `Next.js`，不要動。
4. **Root Directory** 保持 `./`。
5. **Build Command**：`npm run build`（預設）；**Install Command**：`npm install --legacy-peer-deps`（重要！因為 React 19 + klinecharts peer deps）。

> 💡 在 Vercel Project Settings → General → **Install Command** 欄位手動填入：
> ```
> npm install --legacy-peer-deps
> ```

---

## 步驟 3：設定環境變數（規範 6）

在 Vercel **Project Settings → Environment Variables** 加入：

| Key | Value | 範圍 | 必填 |
|-----|-------|------|------|
| `FINMIND_TOKEN` | 你在 [finmindtrade.com](https://finmindtrade.com) 註冊後拿到的 token | Production + Preview | ⭕ 建議（無 token 走匿名額度，會頻繁 429） |
| `TELEGRAM_BOT_TOKEN` | 從 [@BotFather](https://t.me/BotFather) 用 `/newbot` 建立後拿到的 token，格式 `123456:ABC...` | Production + Preview | ⭕ 開啟推播必需 |
| `TELEGRAM_CHAT_ID` | 你的個人 chat id（用 [@userinfobot](https://t.me/userinfobot) 查），群組 id 為負數 | Production + Preview | ⭕ 開啟推播必需 |
| `FINMIND_API_BASE` | `https://api.finmindtrade.com/api/v4/data` | 全部 | ❌ 預設值已正確，不用設 |

設好後點 **Save** → 回到 Deployments 頁觸發 **Redeploy**（讓新 env 生效）。

---

## 驗收清單

部署完成（網址會是 `https://quant-terminal-xxxx.vercel.app`），逐項驗證：

- [ ] 首頁三欄佈局正常顯示
- [ ] 左側 watchlist 載入 6 檔真實 FinMind 報價（`Network` panel 看 `/api/quotes` 回 200）
- [ ] 中央 K 線圖載入，5 條均線（5/10/30/60/240）+ Volume 副圖
- [ ] 點選不同 symbol 圖表會切換
- [ ] 在右側勾滿 A 級條件，**右上 Bot 標籤從 IDLE 變 ✓「A 級觸發」+ 時間戳**，Telegram 收到訊息
- [ ] 在 S0 → S1 → S2 → S3，A 級且無 NO TRADE 旗標下點 S4，**Bot 標籤顯示 ✓「進場 S4」**，Telegram 再收到一則
- [ ] 若 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 未設定，UI 不會崩潰，只會顯示 ⊘「disabled」黃標

---

## 常見問題

**Q: 部署後 watchlist 一直顯示骨架屏（loading）？**
A: 看 Vercel **Functions Logs**，多半是 FinMind 匿名限流。設 `FINMIND_TOKEN` 即可。

**Q: Telegram 推送不到？**
A: 三件事檢查：
1. 你已先在 Telegram 中對 bot 按 `/start`（否則 bot 不能主動發訊息給你）。
2. `TELEGRAM_CHAT_ID` 正確（個人是正整數，群組是負整數含 `-100` 前綴）。
3. Vercel env vars 設完一定要重新 deploy。

**Q: `npm install` 失敗 `ERESOLVE peer dep`？**
A: 確認 Vercel 的 Install Command 是 `npm install --legacy-peer-deps`。

**Q: 想本地預覽 production 模式？**
A:
```powershell
npm run build
npm run start
# 或設定本地 env：
$env:TELEGRAM_BOT_TOKEN="..."; $env:TELEGRAM_CHAT_ID="..."; npm run start
```

---

## 安全提醒

- `.env.local` 已在 `.gitignore` 內，**永遠不會** commit 進 GitHub。
- Telegram token 只存在 Vercel env vars 與你的本地 `.env.local`，client bundle 不會含有任何 token。
- `/api/telegram` 是 server-only route handler，前端只能傳結構化 payload（`grade-a` / `entry-s4` / `raw`），無法注入任意 HTML / token。
