# PROGRESS — 微台指模擬交易平台（sim-trade 模組）

**最後更新**：2026-06-11

> 這份是「跨對話的進度記憶」。新對話說「繼續 sim-trade」，Claude 先讀這份再接手。
> 分工：策略決策 / 踩坑 → `LESSONS.md`（規則檔）；模組進度 / 狀態 → 本檔。兩者**不混**。

---

## 模組定位
微台指（TMF）單人 SMC 當沖訓練器：**歷史回放（優先）+ 即時盤（後期）**。僅本機、僅行情、**永不真實下單**。
與 `backend/sim_book.py`（Telegram 紙上模擬倉）是**不同物**，不可合併。

---

## 關鍵架構決策（已與擁有者確認，實作不可擅改）

| 決策 | 內容 | 理由 |
|---|---|---|
| 模組落點 | `backend/sim_trade/`（獨立 package） | 要 import Shioaji wrapper、與 backend 同 venv；LESSONS §2.9「Shioaji 盤中屬 backend 領域」 |
| 資料庫 | 獨立 `data/sim_trade.duckdb`（非 `tw_stock.duckdb`） | 高頻回放寫入與每日 pipeline 解耦、崩潰隔離；連線沿用 `pipeline/store.py` 慣例 |
| K 線存法 | `kbars_tmf` 1 分 K 為唯一真實來源，高週期即時聚合（`time_bucket` 對齊盤別開盤） | 單一真實來源、零未來函數易保證 |
| 夜盤歸屬 | `session_date` = 開盤日（夜盤 15:00→次日 05:00 整段綁開盤日） | 回放直覺；⚠️ 與期交所官方（夜盤算**次一交易日**）差一天，對帳須用 `sessions.taifex_trading_day()` |
| 變速語意 | `speed` = bars/sec（非倍數），UI 標「N 根/秒」 | 「1 根/秒」=現實 60 倍速，叫「1x」會誤導；預留真實速度 1 根/60 秒 |
| 回放後端 | 獨立 FastAPI app on **:8090**（與 tv_chart :8080 分開） | 回放**有狀態**，不混無狀態 UDF 服務 |
| 前端圖表 | **lightweight-charts**（裝在 Next.js `src/`） | 免授權、wantgoo 同款；tv_chart 用的授權版 Charting Library 不用 |
| 資料源 | Shioaji **TMFR1** 近月連續合約 | 自動轉倉；`contract_month` 留稽核、轉倉推 `contract_switch` 事件 |
| 零未來函數 | cursor 切片，所有聚合/標記只取 `ts ≤ cursor` | 結構上不可能讀到未來，不靠自律 |
| 誠實回放 | seek 倒退設 `sim_sessions.rewind_occurred`，績效分「乾淨/有回看」 | 防統計自我膨脹 |

---

## 各 Phase 狀態

| Phase | 內容 | 狀態 |
|---|---|---|
| **1** | 資料層 + 回放引擎 | ⚠️ **後端完成、前端未做 → 尚未完全驗收**（原驗收含「可流暢回放」需前端肉眼看） |
| 2 | 撮合引擎 + 成本模型 | ⛔ 未開始（**進場前必修 KL#3**，見下） |
| 3 | 部位 / 日誌 / 績效 | 未開始 |
| 4 | 自動出場（OCO + ATR trailing） | 未開始（**依賴逐桶 bar-close 事件**） |
| 5 | SMC 疊圖 | 未開始 |
| 6 | 即時盤 | 未開始 |

**Phase 1 已完成**：DuckDB schema（`kbars_tmf` / `sim_data_gaps` / `sim_sessions`）、Shioaji TMFR1 回補、回放 WS 協定 + 引擎、聚合、單元/整合測試 **42 passed**。
**Phase 1 未完成**：lightweight-charts UI 未做；正規化修正後需**重新回補驗證**（刪 `data/sim_trade.duckdb` 再跑）。

**2026-06-11 真資料首跑發現（已修）**：`_resolve_contract` 一次解析 TMFR1 成功（5277 rows / 5 days / 0 gaps）。但驗出 **Shioaji 1 分 K 時戳標在「bar-close」**（兩盤開盤瞬間都無 K、首根晚 1 分、間隔 60s）。`fetch_tmf.df_to_rows` 已加 **−60s 正規化成 bar-open**（聚合對齊修正 + 救回每盤尾端那根）。⚠️ 既有 `shioaji_fetcher._resample_3m`（M3）吃同款 close-label，可能有相同位移——目前未動（內部一致就不影響 SMC 邏輯），待決定是否稽核。

**檔案位置**：`backend/sim_trade/`（models / sessions / aggregate / protocol / schema.sql / replay / db / fetch_tmf / server + `tests/`）。

---

## 已知限制清單

1. **真資料部分驗收**（2026-06-11）：`_resolve_contract` 已在真連線驗證、bar-close 慣例已修；**待重新回補驗證**（日盤應變 300 根 / 08:45 起）+ UI 肉眼確認對齊。
2. **夜盤跨兩天回補**：午夜後段由次日回補補齊；最新一天夜盤需隔天才完整。
3. ⚠️ **高週期 closed 語意簡化**：`advance` 單步跨多桶缺口時只標前一桶 closed。圖表渲染正確，但**逐桶 bar-close 事件不完整** → 見下方 Phase 2 進場檢查清單。
4. **前端未做**。
5. **DuckDB 單寫者**：回補與唯讀回放 server 勿同時寫（單人本機無妨）。

---

## ⛔ Phase 2 進場檢查清單（動撮合引擎前必先做）

1. **[BLOCKING] 修 KL#3 — 補齊逐桶 bar-close 事件**
   - 做什麼：每個高週期 bucket 在收盤瞬間推明確 `closed=true` 事件。
   - 為什麼 blocking：**Phase 4 ATR trailing stop「每根 K 收盤才更新停損線」，出場引擎吃的就是 bar-close 事件**；不修 → ATR 漏觸發、停損不動 → 出場錯誤。
   - 影響檔案：`replay.py::_bar_events`（目前只在 aggregate 成長時補前一桶），改成可靠的「桶關閉」偵測。
2. 撮合用**同一個 cursor**，限價/觸價只能用「當下這根」判斷（守零未來）。
3. 成本模型：期交稅 = 契約價值 × 0.00002（買賣各課一次）、手續費預設 NT$20/口/邊（設定檔可調）。

---

## 下一步（依序，不可跳）

1. **真資料驗收**：擁有者跑 `fetch_tmf --days 30` + 啟 server，貼輸出 → 調 `_resolve_contract`。
2. **最小 lightweight-charts 回放 UI**：補完 Phase 1 原始驗收（流暢回放、週期切換肉眼對齊）。
3. **Phase 2 撮合**：先清上方 Phase 2 進場檢查清單（含修 KL#3）再寫程式碼。

---

## 環境狀態

- **venv（唯一）**：`tw-stock-signal/.venv`（Python 3.14.4）；backend/ 與 sim_trade 同此 venv 跑
- **依賴**：duckdb 1.5.2 / pandas 3.0.2 / fastapi 0.136.1 / shioaji 1.3.3 / pytest 9.0.3 / httpx 0.28.1（pytest、httpx 本次新裝）
- **secrets**：Shioaji 憑證放 `.env.local`（`SHIOAJI_API_KEY` / `SHIOAJI_SECRET_KEY` 或 `SHIOAJI_API_SECRET`），**絕不 hardcode**；帳號需有**期貨行情權限**
- **DB 路徑**：預設 `data/sim_trade.duckdb`，可用環境變數 `SIM_TRADE_DB` 覆寫（測試用）
- **指令**：
  - 回補：`python -m backend.sim_trade.fetch_tmf --days 30 -v`
  - 啟 server：`python -m uvicorn backend.sim_trade.server:app --host 127.0.0.1 --port 8090`
  - 測試：`python -m pytest backend/sim_trade/tests -q`
  - 看可回放 session：瀏覽器開 `http://127.0.0.1:8090/sim/sessions`

---

## 接手方式（給擁有者）
新對話貼「**繼續 sim-trade**」→ Claude 先讀本檔 + `LESSONS.md` → 從「下一步」第一項未完成處接續。

---
> 註：本檔 2026-06-11 起改記錄 sim-trade 模組。先前「Quant Terminal A 級掃描面板」進度（2026-05-07）已封存於 git 歷史，需要時 `git show 98789b7:PROGRESS.md`。
