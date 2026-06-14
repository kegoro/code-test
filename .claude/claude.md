## 對話啟動規則（最優先）
- **每次新對話開始前**，先 Read 專案根目錄的 `LESSONS.md` 與 `雷老闆心法.md`
- 該檔案包含跨對話的策略決策、踩坑紀錄、待驗證事項；`雷老闆心法.md` 是型態/進出場/財務指標的判斷依據
- 完成回測 / 改策略 / 發現新坑後，**主動**詢問是否要更新 `LESSONS.md`

### 「繼續 XXX」恢復規則（重要）
- 使用者說「**繼續**」或「**繼續 XXX**」時，**先讀對應的 PROGRESS 檔再動手**，不要反問 scope、不要從零重建：
  - 「繼續缺貨雷達」→ 先 Read `PROGRESS-shortage-radar.md`
  - 「繼續 sim-trade / 模擬交易」→ 先 Read `PROGRESS.md`
  - 其他「繼續」→ 先 Read 根目錄所有 `PROGRESS*.md` 找對應主題
- 這些 PROGRESS 檔已記錄完整進度/決策/下一步，**讀完直接接手**。使用者不寫程式，無法自己補上下文，所以「先讀檔」優先於「問使用者」。

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