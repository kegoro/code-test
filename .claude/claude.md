## 對話啟動規則（最優先）
- **每次新對話開始前**，先 Read 專案根目錄的 `LESSONS.md` 與 `雷老闆第二大腦/00-索引.md`
- `LESSONS.md` 含跨對話的策略決策、踩坑紀錄、待驗證事項
- `雷老闆第二大腦/` 是 Obsidian vault（型態/財務指標/選股法/案例/紀律 互連卡片），是型態/進出場/財務指標的判斷依據。從 `00-索引.md` 進入，需要哪個概念再 Read 對應卡片（如 `財務指標/合約負債.md`）
  - 舊單檔 `雷老闆心法.md` 已重構進此 vault，保留作備份，**以第二大腦為準**
- 雷老闆心法有更新（新書頁/新案例）時，更新對應卡片並在 `00-索引.md` 補連結
- 完成回測 / 改策略 / 發現新坑後，**主動**詢問是否要更新 `LESSONS.md`

### 「繼續 XXX」恢復規則（重要）
- 使用者說「**繼續**」或「**繼續 XXX**」時，**先讀對應的 PROGRESS 檔再動手**，不要反問 scope、不要從零重建：
  - 「繼續缺貨雷達」→ 先 Read `PROGRESS-shortage-radar.md`
  - 「繼續 sim-trade / 模擬交易」→ 先 Read `PROGRESS.md`
  - 其他「繼續」→ 先 Read 根目錄所有 `PROGRESS*.md` 找對應主題
- 這些 PROGRESS 檔已記錄完整進度/決策/下一步，**讀完直接接手**。使用者不寫程式，無法自己補上下文，所以「先讀檔」優先於「問使用者」。

## Telegram bot 維護規則（重要）
- **新增 / 修改 / 刪除 Telegram 指令（CommandHandler / MessageHandler）或排程後，自動重啟對應 bot 並驗證 polling，不用先問使用者。** 改了 code 不重啟＝使用者收不到新功能（如 `/fin` 加好但 bot 沒重啟就等於沒有）。
- 哪支 bot 看 LESSONS §1.5 判斷：`/fin`、鑽豹報告、N字/缺貨、txf、模擬倉 → **backend/smc_bot**；台股盤後 daily 訊號 → **tw-stock-signal daemon**。
- **正確重啟方式（2026-06-15 修好並實測）**：先停舊 smc_bot 程序 → 跑 / 雙擊 `launch_smc_bot.vbs`（→ watchdog `start_smc_bot.bat` → python，內建 crash 自動重啟 + 開機自啟）→ 等 ~20 秒確認 `_smc_bot.watchdog.log` 出現 `Application started`。⚠️ **啟動檔（.bat / .vbs）永遠只能 ASCII、不可放中文** —— 中文 + Windows Big5 編碼會讓 cmd 解析中斷、bot 起不來且無錯誤畫面（這是過去「一直起不來」的真因，詳見根目錄 `反覆踩坑.md` 第 1 條）。
- 重啟後跟使用者回報：哪支 bot、PID、註冊幾個指令。

## 回覆規則
- 只輸出需要修改的程式碼片段
- 不要前言、不要解釋、不要摘要
- 有多個修改點時用 `# 檔案名:函數名` 標示位置

## 專案描述（自動推斷）

**用途**：SMC（Smart Money Concepts）量化交易系統，標的涵蓋台股（TWSE）與加密貨幣（BTC/ETH/SOL/BNB）。

**技術棧**：
- 後端：Python（SMC pipeline / Shioaji TWSE / Binance via ccxt / FinMind / Telegram bot）
- 前端：Next.js + React + TypeScript（圖表 dashboard、SMC 結構視覺化、模擬倉介面）

**核心模組**：
- `backend/smc_analyst/setups/*.py` — 7 個 SMC pure-function setup（N-Pattern 為當沖主力、Order Block、Sweep Reversal、Breaker、Mitigation 等）
- `backend/smc_bot.py` — Telegram 操作介面（使用者全程靠 Telegram 指令）
- `backend/sim_book.py` / `sim_monitor.py` — 紙上模擬倉系統
- `backend/aistockmap_scraper.py` — 每日題材爬蟲（Playwright）
- `tw-stock-signal/` — 訊號排程
- `src/` — Next.js 前端 dashboard

**使用者背景**：不寫程式，靠 Telegram 推播驅動策略執行；當前處於紙上模擬期（2026-05-20 起，至少 1 個月）。

**詳細策略決策、踩坑記錄請見 `LESSONS.md`**。