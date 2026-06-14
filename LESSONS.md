# SMC 系統 — LESSONS 教訓記錄

> 跨對話的「策略決策 / 踩過的坑 / 待驗證事項」彙整。
> Claude 每次開新對話前必須先讀這份檔案，避免重複踩坑、保留前後文。
> 使用者要更新只要說：「把 OOO 記到 LESSONS.md」。

**最後更新**：2026-06-14（鑽豹第三刀技術檢核 + 接入 07:00 盤前報告 + ⚠️ 兩支 bot 架構釐清 §1.5）
**對應 git commit**：**04b5a38**（feat: 當沖系統第一版閉環）+ backtest 優化 + crypto 驗證 + OBV 背離 PoC + 批量驗證未提交

---

## 1. 程式碼 / 工程決策

### 1.0 環境坑（2026-06-13）

| 坑 | 症狀 | 根因 | 對策 |
|---|---|---|---|
| **venv 未啟動** | `ModuleNotFoundError: No module named 'pandas'` | 用了系統 Python 而非 tw-stock-signal venv | 每次開終端機先跑 venv 啟動指令；所有 `backend/` 腳本頂端加 `env_guard.require(...)` 早期中止 |
| **yfinance 新版 API** | `'str' object is not callable` | `yf.download()` 在 ≥0.2.x 行為改變 | 改用 `yf.Ticker(ticker).history()` — 跨版本穩定；`layer_a.py` 已採用此寫法 |

**venv 啟動指令**（每次開新終端機都要跑）：
```
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& 'c:\Users\sfudally\Desktop\code test\tw-stock-signal\.venv\Scripts\Activate.ps1')
```

---

### 1.1 A1 加入 C7d Order Block 過濾
- **來源**：commit b15382d
- **原本**：A1 strategy 勝率 ~47%，期望值偏負
- **改動**：在訊號觸發條件加上 C7d（7 天 Order Block）過濾
- **結果**：勝率提升到 **63.9%**，期望值由負轉正
- **道理**：Order Block 代表機構掛單區域，沒有 OB 支撐的訊號品質低
- **待補**：對應的 backtest summary 檔案目前 `reports/` 找不到，需重跑或補存

### 1.2 改用 Shioaji 解鎖真實 M3 回測
- **來源**：commit c3a0500
- **背景**：FinMind 免費 tier 無法取 1/3 分鐘 K 線（API 回 400）
- **改動**：改用永豐 Shioaji + M3 歷史快取
- **範圍**：盤中 09:00–13:35 自動掃描
- **道理**：FinMind 升級付費 vs 已有 Shioaji 帳戶 → 後者成本低

### 1.3 SMC pipeline 採用 7-setup 純函式架構
- **位置**：`backend/smc_analyst/setups/*.py`
- **setups**：sweep_reversal / ob_continuation / premium_fade / breaker / 等
- **道理**：每個 setup 寫成 pure function 方便回測 + 單元測試

### 1.4 鑽豹第三刀技術檢核（2026-06-14）
- **位置**：`backend/diamond_blade3.py`（純標準庫 + requests，FinMind 日K）
- **三條件**（照《鑽豹三刀流》第3章書本定義）：
  1. **均線多頭排列** = MA5>10>20>60 且股價站上 MA5
  2. **MACD** = DIF>0 且柱>0（零軸上方）；剛由負轉正標 🔥金叉
  3. **乖離率** = 短期(6日)BIAS 平均線 > 長期(24日) 且當日 BIAS>0；剛上穿標 🔥金叉
- **接點**：已嵌入 `morning_report.generate()` 第四段，07:00 盤前報告自動掃「8 檔固定追蹤清單 + 今日大漲前6名」
- **用法**：`python -m backend.diamond_blade3 [代號...] [--tg]`
- **定位**：第三刀是「加碼確認」訊號，需配第一刀(賺賠比)+第二刀(基本面)，不可單獨進場
- **環境坑**：`venv/Scripts/python.exe` **沒有** requests/pandas；要用系統 Python `C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe`（有 requests+pandas+bs4）。morning_report / diamond_blade3 都要用系統 Python 跑

### 1.5 ⚠️ 兩支獨立 Telegram bot — 動 bot 前務必先分清（2026-06-14）

> **這條最容易踩坑。任何「重啟 / 套用報告 / 改排程」的需求，先讀這條再動手。**

專案有 **兩支完全獨立的 Telegram bot**，用 **不同 token**，可同時常駐不衝突：

| Bot | 啟動方式 | Token | 負責什麼 | 07:00 做什麼 |
|-----|---------|-------|---------|-------------|
| **tw-stock-signal** | `tw-stock-signal/main.py --daemon`（→ `notifier/bot_handler.py` + `scheduler/daily_job.py`） | `TELEGRAM_BOT_TOKEN=879224...` | 台股訊號排程、抓資料入 DuckDB | **fetch_job 抓資料**（與鑽豹報告無關） |
| **backend/smc_bot** | `python -m backend.smc_bot`（用系統 Python313） | `SMC_TELEGRAM_BOT_TOKEN=850902...`（在 `smc_bot.py:124` 優先讀此，特意分開避免衝突） | **鑽豹盤前報告**、台指期 daily_signal、第三刀、N-pattern watcher | **`_job_morning_report` 鑽豹盤前報告（含第三刀）** |

**判斷規則**：
- 需求若提到 **鑽豹盤前報告 / morning_report / diamond_blade3 / 台指期 /txf / 第三刀** → 動的是 **`backend/smc_bot`**
- 需求若提到 **台股每日訊號排程 / 抓盤後資料** → 動的是 **tw-stock-signal daemon**

**踩過的坑（2026-06-14）**：使用者說「重啟 bot 套用新報告」，當下在跑的只有 tw-stock-signal daemon（PID 用 `Get-CimInstance` 查 CommandLine 確認）。差點誤重啟它——但它根本不含鑽豹報告。真相是 `backend/smc_bot` **從未常駐跑過**，需首次啟動。

**啟動 / 重啟 backend/smc_bot 標準步驟**：
```
# 1. 查現有程序（看 CommandLine 才能分辨是哪支）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? {$_.CommandLine -like '*smc_bot*'} | Select ProcessId,CommandLine
# 2. 若有舊的先 Stop-Process -Id <pid>
# 3. 用系統 Python 背景啟動
C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe -m backend.smc_bot
# 4. 讀 log 確認：'SMC bot polling …' + 'Application started' + 'Added job "_job_morning_report"'
```
- 因兩支 token 不同，啟動 smc_bot **不會** 影響 tw-stock-signal daemon（不會 409 Conflict）。
- 同一支若重複啟動才會 409（同 token 兩個 polling）。

**`--tg` 送訊息一律走 SMC bot（2026-06-14 統一）**：
- `daily_signal._send_telegram` 已改為優先讀 `SMC_TELEGRAM_BOT_TOKEN` / `SMC_TELEGRAM_CHAT_ID`（fallback 才用舊的 `TELEGRAM_*`）。
- 因此 `morning_report --tg` / `daily_signal --tg` / `diamond_blade3 --tg` 全部從 **SMC bot（850902）** 發，與 07:00 排程 `_job_morning_report` 同一支，來源一致。
- **不要改回 `TELEGRAM_BOT_TOKEN`**，否則手動與排程會變兩支不同 bot、使用者收到不同對話視窗的重複訊息。

---

## 2. ⭐ 2026-05-16 — 雷老闆面談後的策略升級【最新、最重要】

> 📖 **雷老闆「書摘」型態學/進出場/紀律 → 見獨立檔 [`雷老闆心法.md`](雷老闆心法.md)**
> 做型態判斷、進出場、寫分析時**必須對照該檔**（W底/M頭/三角收斂、頸線停損、實體K確認、方向確立後才進場）。
> 本節 §2 = 面談「選股哲學」；`雷老闆心法.md` = 書摘「進出場型態」，兩者互補。

### 2.1 雷老闆 5 個核心原則（過濾完逐字稿後的精華）

| 原則 | 內容 | 對 SMC 系統的衝擊 |
|------|------|----------------|
| **A. 「缺」字哲學** | 真缺貨 → 廠商漲價 → 營收暴衝（顯卡、AI 伺服器零件） | 缺貨股 = 基本面驅動，技術指標是噪音 |
| **B. 大戶買激情股不買牛皮股** | 要有「大客戶/新產品/新政策/新技術」其中一個 | 牛皮股 SMC 可能更穩；激情股要不同對待 |
| **C. 不抓最低最高** | 散戶死於「等再便宜」+「再漲一點」；大戶不這樣做 | **Premium Fade 本質就違反這條** |
| **D. 獲利了結時機** | 全市場狂熱關注（鄉民法說會、媒體鋪天蓋地）= 大戶離場 | SMC 的結構性出場可能跟「熱度頂點」差距很大 |
| **E. 過水單陷阱** | 營收暴增但毛利低 = 假業績，季報必崩 | 純看月營收選股會被騙，要看毛利率 |

（其他章節：拜訪公司讀心術、司機哲學、貸款買賓士、停損是申論題 — 都是個人經驗故事，沒法寫成程式規則，不收。）

---

### 2.2 決策一 — 選股 × 進場：題材白名單 + SMC 只跑白名單

**使用者已決**：先用題材+籌碼+基本面選出白名單（約 10 檔），SMC 只在白名單上跑訊號。

**為什麼這樣選**：
- 對應雷老闆原則 A、B：把不適合 SMC 的股票（基本面驅動的妖股）擋在外面
- 比「全市場掃描 + 權重」乾淨：權重設定容易主觀
- 缺點：白名單選錯就全錯（高度依賴選股品質）

**程式對應（尚未實作）**：
- 在 `backend/scanner_scheduler.py` 加 `SCANNER_WHITELIST` env var（逗號分隔 symbol）
- 沒設白名單時退回現有行為（全市場掃描）
- 白名單來源**未定**（見 2.6）

---

### 2.3 決策二 — 2382 廣達：留著但只買不放空（順大趨勢）

**使用者已決**：2382 不剔除掃描清單，但禁用所有放空 / fade 類訊號（Premium Fade、做空版的 Sweep Reversal 等），只接受多單訊號。

**為什麼這樣選**：
- 對應雷老闆原則 A（AI 缺貨核心 → 大趨勢向上）
- 比「直接剔除」保守，不錯過 AI 大行情
- 比「降低部位」乾淨，不需要動部位邏輯

**✅ 已執行 2026-05-16**：
- 新增 `backend/smc_analyst/symbol_config.py`：`SYMBOL_DIRECTIONS` dict + `is_direction_allowed(symbol, direction)`
- `pipeline.py` 在每個 setup 回 `SetupMatch` 後加 direction filter（在 hard gates 之前）
- 2382 設為 `frozenset({"long"})` — 只接受多單訊號
- 其他 symbol 未列出 → 預設兩邊都允許（向後相容）
- 要再加 symbol 限制：直接編輯 `SYMBOL_DIRECTIONS` dict 即可

---

### 2.4 決策三 — 出場條件：技術 AND 熱度 兩者都符合才繼續持有

**使用者已決**：持倉期間，**技術結構未破壞** AND **熱度未到頂** 兩條都成立才抱單；任一警報出現就出場。

**為什麼這樣選**：
- 對應雷老闆原則 D（鄉民法說會 = 大戶離場）
- 等於「寧可早走也不抱跌」，偏保守
- 風險：可能太早出場錯失主升段；但對使用者來說最大威脅是抱不住停損，所以這選擇合理

**程式對應（尚未實作）**：
- 「技術結構未破壞」= 現有 SMC invalidation 邏輯（已有）
- 「熱度未到頂」= **未建**，需要熱度指標（見 2.6）
- 結構建議：寫 `exit_guard.py`，回傳 `(should_exit: bool, reason: str)`

---

### 2.5 決策四 — Premium Fade + Discount Rally 禁用 ✅ 已執行 2026-05-16

**使用者已決**：禁用 `PremiumFade`（強勢段反手空）和 `DiscountRally`（弱勢段反手多）。
兩者在 `premium_fade.py` 同檔案，共用 `_evaluate(direction=...)`，鏡像對稱，都違反雷老闆 C 原則。

**為什麼這樣選**：
- 對應雷老闆原則 C（不抓最低最高）
- 回測證據：PremiumFade 在 2330/2317/2382/2454 共觸發 50+ 次，**全 0% 勝率**
- DiscountRally 樣本只 1 次（2308 也敗），不足以證明但邏輯同病
- 比「改條件」乾脆，省下調參時間

**已執行內容**：
- `backend/smc_analyst/setups/__init__.py`：註解掉 `PremiumFade, DiscountRally` 的 import 與 ALL_SETUPS 註冊
- **保留** `premium_fade.py` 檔案不動（要重啟只要解開 2 行註解）
- 未來想重啟需要明確證據（不同市場 / 不同條件下有勝率）

---

### 2.6 ⚠️ 衍生待辦（這 4 個決策真正落地前必須先解的事）

- [x] **題材白名單怎麼來？** ✅ 2026-05-16 晚間採 (b) `aistockmap.com` 爬蟲（Playwright），詳見 §2.7
  - 已完成模組：`backend/aistockmap_scraper.py` / `theme_filter.py` / `aistockmap_report.py`
  - Telegram 指令：`/aistockmap`（手動觸發）
  - **未解**：題材→個股映射（aistockmap 個股大多 Premium 鎖定）
- [ ] **「熱度頂點」指標怎麼建？** ⚠️ 當沖定位後此項**降級為 P2**（時間框架不對）
- [ ] **基本面 agent 要不要做？** ❌ 當沖定位後**不做**，當沖看的是當日題材熱度不是基本面
- [ ] **per-symbol direction 設定 UI**：⚠️ 當沖兩邊都要做（多空），§2.3 的 2382 only-long 設定要重新評估

---

## 2.7 ⭐ 2026-05-16 晚間 — 當沖策略架構確認【最關鍵的定位】

**這次對話最重要的情報：使用者玩台股是「當沖」，不是波段。** 之前 §2.1-2.6 的決策很多是波段視角，必須重新審視。

### 2.7.1 使用者策略主軸：N 字戰法 + SMC Demand Block + 隔日沖警告

**4 階段流程**：

| 階段 | 時間 | 動作 | 對應現有系統 |
|---|---|---|---|
| 1. 備課 | 昨晚 22:00 / 今晨 08:30 | aistockmap AI 分析 → 列今日 watchlist | ✅ scraper 完成，⚠️ 個股映射未解 |
| 2. 觀察 | 09:00 開盤 | 漲 2-3% **不追**，標記「N 字第一拍候選」 | ❌ 沒做 |
| 3. 判隔日沖 | 09:00-09:30 | 偵測開高走低 + 量價衰竭 → 推警告避免接刀 | ❌ 沒做 |
| 4. 進場 | 09:30-12:30 | 跌到 Demand Block + HH/HL 成立 → 推進場 | ⚠️ SMC 有 DB，但未限定 watchlist + 無 N 字 setup |

**約束條件**：
- 資金 < 50 萬（影響可交易股票池）
- 不能盯盤（**必須 Telegram 即時推播**驅動，不能 polling 介面）

### 2.7.2 對舊決策的衝擊（必須重新評估）

| 舊決策 | 波段視角 | 當沖視角 | 處置 |
|---|---|---|---|
| §2.3 2382 only-long | ✅ 順大趨勢 | ❌ 當沖兩邊都做 | **改：當沖模式下忽略 per-symbol direction** |
| §2.4 出場用「熱度頂點」 | ✅ 鄉民法說會=大戶離場 | ❌ 時間框架太慢（熱度週期 = 數日，當沖 = 數小時） | **改：當沖出場 = 13:00 強制平倉 + DB 破停損** |
| §2.5 禁用 Premium Fade | ✅ 抓波段最高賠錢 | ❓ 盤中過熱 fade 是正規當沖手法 | **待驗證：分時段重測 Premium Fade 在 09:30-12:30 的勝率** |

### 2.7.3 雷老闆原則對當沖的對應

| 原則 | 當沖該怎麼用 |
|---|---|
| A 缺貨 | 看「**今天剛爆**」的缺貨新聞（不是長期趨勢），用 aistockmap daily 焦點 |
| B 大客戶/新產品/新政策/新技術 | 同上，題材必須**當日新發生**才有日內波動 |
| C 不抓最低最高 | ✅ **完美對應 N 字戰法**：開盤漲 2-3% 不追，等回測 Demand Block |
| D 大戶離場（鄉民法說會） | ⚠️ 當沖週期太短用不到 |
| E 過水單 | ⚠️ 當沖不看季報，用不到 |

### 2.7.4 當沖最容易踩的坑（使用者必須知道）

1. **滑價吃掉 30%+ 預期獲利**：手續費（買賣 2×0.1425%×6 折）+ 證交稅減半（0.15%）+ 滑價 ≈ 一趟 0.3% → 目標報酬必須 > 0.6%
2. **過度交易**：每天 5 筆以上 → 心態崩 → 訂「**一天最多 3 筆**」硬規則
3. **不能套牢過夜**：當沖停損 1-2% 就走，套牢就違反當沖定義
4. **Demand Block 破要立刻砍**：使用者原策略只講「DB 買進」沒講「DB 破停損」，必須補

### 2.7.4b ⚠️ 進場前 4 條鐵則（2026-05-20 復盤後新增）

**背景**：使用者 2026-05-20 一筆衝動進場（看「連續小紅 K 態勢」9:00-10:00 進、沒設停損）+ 套牢後同檔加碼凹單，兩筆都賠。診斷：**只下了「進場」決定，沒有「停損、目標、部位、若錯怎辦」** → 套牢時沒有預設答案、只能靠情緒決策。

**按順序問自己、任一個答 No → 不進**：

1. **是 bot 推的訊號嗎？**（N 字 watcher / OB watcher / DB approach）
   → 沒推就不進。衝動看 K 線 = 跳過 N 字 Beat 2 = 接刀手版本。

2. **進場前我有沒有「寫下來」停損價？**
   → 沒寫就不進。不是「心裡想一下」，是真的打字寫出（Telegram 自己對自己送 / 紙條 / 備忘錄）。

3. **從進場到停損會虧多少 %？**
   → > 2% → 縮部位或不進。當沖一趟手續費+稅+滑價 ≈ 0.3%、賠 2% = 7 趟成本沒了。

4. **今天已經第幾筆？**
   → ≥ 3 筆收手、不管賺賠。對應 §2.7.4 #2「一天最多 3 筆」。第 4 筆永遠是報復性 / 強迫進場、永遠虧。

**禁止行為（絕對不能）**：

- ❌ 套牢加碼拔成本 — 「降低均價」= 部位變兩倍 = 風險變兩倍。所有當沖殺手共同死法
- ❌ 違反停損價（凹單）— 「再等一下說不定反彈」= 損失迴避偏誤，永遠繼續賠
- ❌ 同一檔反向（多空互轉）— 你今天看錯方向、不會 5 分鐘後就看對

### 2.7.4c ⚠️ 風險預算 + FOMO 對抗（2026-05-20 復盤後新增）

**使用者的金額標準**（2026-05-20 訪談確認）：
- 資金 40 萬（30-50 萬區間）
- 年最大虧損 8 萬（資金 20%）— **bright line、超過停玩**
- 月期望賺 1-3 萬 — **數學上 OK** 但需嚴格執行（勝率 45% + R:R 1:1.5 + 紀律執行率 95%+）
- 單筆風險上限 4,000 元（資金 1%）
- 日損失上限 8,000 元（資金 2%）— **賠到當天收工**

**FOMO 對抗 3 機制**：
1. 開盤前 15 分鐘 bot 推「⛔ 9:00-9:15 禁止交易、等 N 字 watcher 推送」
2. 看到衝高選擇不進時、Telegram 紙上記錄「YYYY-MM-DD HH:MM <symbol> 想進、選擇不進」— 把「不進」變成一個明確決定
3. 拒絕全市場掃描誘惑、每天只看 watchlist（≤ 5 檔）

**今天事件（2026-05-20）**：
- 5 筆交易（超過 §2.7.4 #2 的 3 筆硬規則 67%）
- 第 1 筆 3481 × 3 張 @39（接近最高）— bot 推「別追高」**使用者無視**
- 第 2 筆 2344 華邦電 @118.5 → 114 = -4,763（-4.02%）「無腦進」
- 後續 3 筆：「Telegram 抓不到資料、無邏輯」← bot 故障期間繼續硬幹
- **最致命診斷**：紀律寄託在 bot 上、bot 故障 = 失控 → 系統「外包紀律」而沒「內化紀律」

### 2.7.5 ⭐ 紙上模擬期（2026-05-20 → 至少 2026-06-20）

**狀態**：實盤暫停、只做 Telegram 紙上模擬。

**規則**：
| 項目 | 內容 |
|---|---|
| 資金 | 虛擬 40 萬（跟真實一致） |
| 訊號來源 | **只接受** N 字 watcher / OB watcher / DB approach 推送 |
| 進場流程 | Telegram `/sim_open <symbol> long entry=X stop=Y target=Z size=N` |
| Bot 自動監控 | 觸停損/停利時推「✅ 模擬贏 +XXX / 💀 模擬輸 -XXX」 |
| 每日上限 | 3 筆模擬部位、超過 bot 拒絕受理 |
| 月底成績單 | 總筆數 / 勝率 / 平均 R:R / 期望值 / 紀律執行率 |
| **復實盤條件**（必須同時）| 勝率 ≥ 50% + 期望值 > 0 + 紀律執行率 ≥ 95% |
| 沒達標 | 繼續紙上模擬另一個月、檢討規則本身 |

**已完成（2026-05-20 深夜實作）**：
- [x] `backend/sim_book.py` — 紙上模擬部位簿 + 紀律守門（R:R/單筆風險/日筆數/方向）
- [x] `backend/sim_monitor.py` — cron 每 3 分鐘對 active 部位拉 m3 last close、觸 stop/target 自動結算 + 推 Telegram
- [x] `backend/sim_suggester.py` — **auto 模式**：使用者只給 symbol+direction+entry+size，bot 根據 Bull/Bear OB + ATR 自動算建議 stop/target（R:R 預設 2.0）
- [x] Telegram 指令 `/sim_open` `/sim_close` `/sim_status` `/sim_report`
- [x] Telegram menu 清理（2026-05-20 使用者要求）：只放「無參數可直接執行」的指令，需要參數的（/sim_open /sim_close /ai_analyse /wl_add 等）從 menu 移除、手動打避免誤觸

**還沒做（P1）**：
- [ ] 開盤前 15 分鐘 cron 推「禁止交易、等 N 字 watcher」提醒
- [ ] 復實盤條件達標時自動推「✅ 達標、可考慮回實盤」

### 2.7.5b ⚠️ 2026-05-26 — 使用者提前破規回實盤

**狀態變更**：使用者明示「現在開始恢復交易」、選擇「明知未達標、仍要回實盤」。

**與原規則衝突**（§2.7.5 紙上模擬期條件，**全部未達**）：

| 條件 | 規則 | 2026-05-26 現況 |
|---|---|---|
| 模擬期長度 | 至少到 2026-06-20 | 才 6 天（離規則差 25 天） |
| 勝率 ≥ 50% | 未驗證 | 樣本太小（§2.8.4 證 30 天都不可信） |
| 期望值 > 0 | 未驗證 | 同上 |
| 紀律執行率 ≥ 95% | 未驗證 | 距 §2.7.4c 失控事件僅 6 天 |

**Claude 已盡告知義務**：把規則差距、§2.7.4c 失控事件、樣本不足全部攤開給使用者選；使用者仍選破規。

**仍然強制生效（不因破規而豁免）**：
- §2.7.4b 進場前 4 條鐵則（bot 推、寫停損、虧 < 2%、≤ 3 筆）
- §2.7.4c 風險預算（單筆 ≤ 4,000 / 日 ≤ 8,000 / 年 ≤ 80,000 bright line）
- §2.7.4c 禁止行為（套牢加碼、凹單、同檔反向）
- §2.7.4c FOMO 對抗 3 機制（9:00-9:15 禁、不進就記錄、只看 watchlist）

**自動煞車條件（Claude 下次對話主動提醒）**：
- 單日虧損 ≥ 8,000 → 提醒當天收工
- 連續 3 個交易日虧損 → 提醒回模擬
- 觸年度 -80,000 → 提醒**停玩**（bright line）
- 連續 5 天紀律執行率 < 95%（≥ 1 筆違反 §2.7.4b）→ 提醒回模擬

**檢視點**：2026-06-26（實盤滿 1 個月）做「實盤紀律執行率盤點」— 不是看賺賠，是看執行率。執行率 < 95% 即使賺錢也要回模擬。

---

### 2.7.6 已刪除的舊指令（2026-05-20）

舊版 in-memory watchlist 系統（`/smc_watch` `/smc_unwatch` `/smc_list` `/smc_start` `/smc_stop`）已被持久化版本（`/wl` `/wl_add` `/wl_del` `/wl_clear` + 自動 cron）取代、5 個指令刪除：
- 移除 5 個 cmd handler + 5 個 add_handler + `_bg_task` + `_push_signal`
- code 少 ~70 行
- `self.scanner` 保留給 `/smc_scan` 對單一股號跑結構分析用

### 2.7.5 決策已定（2026-05-16 晚間）

- [x] **Q1 個股映射** ✅ 採 **A. 手動貼股號** — 使用者看完 aistockmap 後在 Telegram 用 `/wl_add 2330 2317` 加入，最快也最準
- [x] **Q2 隔日沖判斷** ✅ 採 **簡化版** — 「前日漲 > 5% AND 今開 > 2%」就標記，1 天能寫完，可訓練使用者直覺
- [x] **Q3 N 字戰法時框** ✅ 採 **M3** — 訊號快、可進場時間長（noise 多但這是當沖必然代價）

### 2.7.6 待做（按優先順序）

**P0 — 沒它整套策略跑不動** ✅ 全部完成 2026-05-16 深夜
- [x] **aistockmap 題材 → 個股映射**（依 Q1 = 手動，由 watchlist Telegram 指令解決，不需額外模組）
- [x] **`data/day_trade_watchlist.json` 機制** → `backend/watchlist.py`（frozen dataclass + 原子寫入）
- [x] **SMC scanner 只掃 watchlist** → `smc_scanner.py::_effective_watchlist()` 每輪重讀檔案；空檔 fallback 到 `SMC_WATCHLIST` env
- [x] **隔日沖警告偵測（簡化版）** → `backend/overnight_holders.py::evaluate()` + Telegram `/overnight_check`

**Telegram 新指令（全部已接好）**：
- `/aistockmap` — 抓題材 + 列點 + HTML 附件 + 提示 `/wl_add`
- `/wl` / `/wl_add` / `/wl_del` / `/wl_clear` — 當沖 watchlist 維護
- `/overnight_check` — 對 watchlist 跑隔日沖警告（前日 >5% + 今開 >2%）

**P1 — 策略升級** ✅ 全部完成 2026-05-16 深夜
- [x] **N 字 setup** → `backend/smc_analyst/setups/n_pattern.py` + `test_n_pattern.py`（7/7 pass）
  - 走「積極派」：last_close 反彈離 L1、未破 H1 即觸發（不等價回 OB）
  - 限定 09:30-12:30，純 long
  - Score：H1+OB 各 3 分（基底 6）；強第一拍/L1>open/HTF/session 加分；HTF 反向半折
- [x] **N 字 watcher（first_beat + db_approach）** → `backend/n_pattern_watcher.py` + `test_n_pattern_watcher.py`（11/11 pass）
  - first_beat：開盤後 m3 H1 漲幅 ∈ [2%, 5%] 且最近 3 根內 → 推「列入觀察等回測」
  - db_approach：close 在 bullish OB 內或上方 0.3×ATR → 推「準備進場」
  - 兩者用 `backend/alert_state.py`（持久化 dedup，預設 60 分鐘窗）
- [x] **接 smc_analyst pipeline**：`pipeline.py::analyse_watchlist()` 優先讀 `data/day_trade_watchlist.json`
- [x] **Telegram 自動推播 cron**：`/analyst_scan` + `/watch_alerts` 手動指令；`JobQueue.run_repeating(180s)` 每 3 分鐘自動跑（盤中時段才動作）
- [x] **盤前 cron**：`scripts/aistockmap_brief.py --slot=morning|evening`（獨立進程，不依賴 bot），含 6h dedup
  - 配 Windows `schtasks /create ... /sc DAILY /st 08:30` 與 22:00 兩個排程（範例見 script docstring）

**P2 — 防護（尚未做）**
- [ ] 13:00 強制平倉提醒
- [ ] DB 破停損推播
- [ ] 重新驗證 §2.5 禁用 Premium Fade 在當沖時段是否仍正確

### 2.7.7 P0 + P1 N 字 setup 實作踩到的坑

1. **`add()` 沒拆逗號內部**：原本 `add(['2330', '2317,2454'])` 會把 `'2317,2454'` 整串當一個 symbol。修法：`add()` 和 `remove()` 內部都先跑 `parse_symbols_arg`，呼叫者不必預先 split。
2. **scanner 動態切換 source**：`SMCScanner.watchlist` 是 dataclass 欄位無法改動態 callable，改用 `_effective_watchlist()` method 每輪 reload 檔案；維持向後相容（無檔案 → env 行為不變）。
3. **隔日沖 today_open 來源**：盤中要用 `m3` 第一根的 open，盤後 fallback 到 daily 最後一根 open。bot `cmd_overnight_check` 已處理。
4. **`Watchlist` frozen dataclass + 原子寫入**：避免半寫檔（中斷 → 下次讀到爛 JSON）。實作用 `.tmp` 後綴寫入再 rename。
5. **N 字 setup 距離條件設計錯**：原本卡 `last_close in [OB.bottom, OB.top + ob_height]`（保守派等回 OB 才進）→ 結果 last_close 已反彈到 102 直接被擋。**正確：N 字戰法積極進場是「反彈起來、未破 H1」，不該等回 OB**。改成 `last_close > L1 and last_close < H1` 即可。
6. **N 字 setup 用 1m bars 內部 resample 到 3m**：未來其他 setup 也要 m3 時，可升級成 `AnalysisContext` 加 `m3` Frame，但目前單一 setup 用就先內部 resample，避免動 context schema。
7. **bull vs bear case raw_score 不同**：HTF aligned 會多 1 分 bonus，所以驗證 counter-trend 半折邏輯時要分別斷言（不能 `bear.score == bull.raw_score // 2`）。
8. **smc_scanner（舊）vs smc_analyst.pipeline（新）兩條線並存**：telegram bot 原本只有舊線（`SMCScanner` + `smc_detector`），新的 7-setup（含 N pattern）在 `smc_analyst.pipeline`。修法：bot 加 `/analyst_scan` 走新線，舊 `/smc_*` 並存不動，未來再決定要不要砍舊線。
9. **JobQueue 需要 extras**：`pip install 'python-telegram-bot[job-queue]'` 才有 `app.job_queue`，否則 None。bot 啟動時 fallback log warning 不 crash。
10. **獨立 brief script 用 `Bot` class**：不啟動 `Application`，直接 `Bot(token).send_message()` 推完即退出 — 適合 schtasks 排程。記得用 `async with bot:` 確保 connection cleanup。

---

## 2.8 ⭐ 2026-05-17 凌晨 — Crypto SMC 跨樣本驗證【最新】

### 2.8.1 背景

使用者問「能不能用 BTC papertrading 驗證策略」→ 跑 BTC/USDT 30 天 SMC 回測，結果 EV+0.33R 看似可行。但測試後續發現兩個關鍵問題，差點上 Testnet 賠錢。

### 2.8.2 發現 A — Backtest vs Production 不一致 bug

**症狀**：原 `backtest.py::_build_ctx_from_slice` 餵 detector 整段成長 slice（0 → t，最多 43200 根），但 production live pipeline (`context.py` `_LTF_DAYS_M1=5`) 只餵最近 5 天 (~1350 根)。

**後果**：backtest 看到 production 永遠看不到的歷史，產生**假象正期望值**。修正後：

| 版本 | Fires | WR | EV |
|---|---|---|---|
| 原 backtest (餵全 slice) | 381 | 13.8% | +0.33R ❌ 假象 |
| 修正後 (對齊 production 1500 根) | 288 | 8.7% | -0.19R ✅ 真實 |

**修法**：`backtest.py::_build_ctx_from_slice` 加 `_LTF_WINDOW=1500` / `_MTF_WINDOW=200`，daily 計算移出 loop 一次性算（`htf_cache`），MTF slice 改 numpy searchsorted。**附帶得到 53x 加速**（5.5h → 6.2min）。

**教訓**：未來新增任何 backtest 工具必須跟 live pipeline 對齊歷史窗口長度。**Backtest 和 live 看到不同東西 = 評估完全失效**。

### 2.8.3 發現 B — TF 是頭號變數（M1 完全沒用）

跑 BTC/USDT M1/M5/M15/M30/1H 30 天對比：

| TF | Fires | WR | EV | avgR:R |
|---|---|---|---|---|
| M1  | 288 | 8.7% | -0.19R | 32.00 |
| M5  | 252 | 16.2% | -0.04R | 19.59 |
| M15 | 104 | 28.6% | +0.47R | 6.10 |
| M30 | 62 | 32.1% | +0.27R | 5.61 |
| 1H  | 28 | 28.6% | +0.06R | 3.41 |

**觀察**：
- M1/M5 噪音太大吃掉 ATR 停損（avgR:R 19-32 = 停損 < 0.05%，crypto 1m bar 一定碰到）
- M15 是 noise vs sample 黃金交叉
- M30/1H fires 太少，整體 EV 下來

### 2.8.4 發現 C ⚠️ — 30 天 backtest 嚴重不可信（最大教訓）

M15 跨樣本驗證：

| 樣本 | Fires | WR | EV |
|---|---|---|---|
| M15 30d | 104 | 28.6% | **+0.47R** ✅ 看似可行 |
| M15 90d | 476 | 11.0% | **-0.34R** ❌ 真實 |
| M15 180d | 714 | 17.1% | +0.44R（但 avgR:R=19.68 是假象）|

**M15 30d EV+0.47R 是 sample bias**：4/17-5/17 BTC 在趨勢段，所有結構型 setup 都吃到甜頭。90 天涵蓋震盪期 → 全部壞掉。

**教訓**：
- **絕不能用 30 天樣本決定要不要上線**，至少 90 天，最好 180 天
- 180d EV+0.44R 看似回到 30d 水準，但仔細看是 avgR:R 19.68 的數學魔術（38 個贏家 × 15R 抵 155 個輸家 × 1R）— **不是真實邊際**（延伸 §3.5）

### 2.8.5 發現 D ✅ — N-Pattern 是 BTC 上唯一跨樣本穩定的 setup

| Setup | 30d | 90d | 180d | 結論 |
|---|---|---|---|---|
| Trendline Break | 44%/+2.30R | 19%/+0.27R | 20%/+0.14R | 30d 騙人 |
| OB Retest | 33%/+0.63R | 11%/-0.26R | 20%/+1.86R | 不一致 |
| Mitigation | 26%/+0.37R | 7%/-0.47R | 11%/-0.44R | 沒邊際 |
| Breaker | 18%/+0.10R | 7%/-0.55R | 12%/-0.23R | 沒邊際 |
| Unicorn | 30%/-0.10R | 10%/-0.58R | 20%/-0.28R | 沒邊際 |
| FVG @ HTF | 0% | 0% | 0% | 死設定 |
| **N-Pattern** | n=1 W1 | **67%/+1.28R** | **50%/+0.69R** | **唯一可信** ✅ |

N-Pattern 原為 TWSE 09:30-12:30 設計，因 `run_btc_backtest.py` 將 `SMC_SESSION_WINDOW_HOURS=4.0` 改成 4 小時 rolling window，跨上 crypto 24/7 仍有效。180 天 28 fires = 約 1 次/週，慢但可信。

**Gate 判斷**：N-Pattern 90d WR=66.7% > 45%，**第一次有 setup 過 Gate**。但要先驗證 ETH/SOL/BNB 不是 BTC 特例（同時跑中）。

### 2.8.6 發現 E — Setup bugs（暫不修，先用 N-Pattern only）

**OB Retest stop placement bug**（`ob_continuation.py:134-139`）：
- Line 134: `entry = ob["top"]`（long 用 OB 頂部當進場）
- Line 135-136: 偵測到 FVG 時 `entry = FVG 中點`
- Line 139: `stop = ob["bottom"] - buffer`
- **若 FVG 中點落在 OB 下方** → entry < stop on long → 即時觸發 stop
- 證據：M1 backtest OB Retest 6 次失敗，4 次 stop < entry 距離 < 0.02%

**Trendline Break long bias**（M1 backtest）：208 次觸發**全 long**，沒一次 short — 結構偵測或 BOS 邏輯可能有方向偏誤。

**處置**：因 N-Pattern 已足夠且 setup 本身就被 §2.8.5 證明不可信，這兩個 bug 留作技術債，不優先修。

### 2.8.7 決策

- [x] **不上 Testnet**（30d 數字是假象，差點賠錢）
- [x] **Backtest 對齊 production**（已修，待 commit）
- [ ] **驗證 N-Pattern 在 ETH/SOL/BNB**（跑中）
- [ ] **如 N-Pattern 跨幣種穩定** → 寫「N-Pattern only crypto bot」規格 → 再上 Testnet
- [ ] **如 N-Pattern 只在 BTC 有效** → 縮小範圍只跑 BTC

---

## 2.9 ⚠️ 兩個系統的職責分工（不要混淆 / 不要合併）【2026-05-26】

**現況**：`backend/` 和 `tw-stock-signal/` 是**兩個並存系統，不是 legacy + new**，不要嘗試合併或互相搬程式碼。

| 系統 | 用途 | 資料源 | 週期 | Telegram bot token |
|---|---|---|---|---|
| **backend/** | 盤中即時 SMC 訊號（N 字 / OB / DB approach）+ 紙上模擬倉監控 | Shioaji M3 即時 | 每 3 分鐘輪詢 | `SMC_TELEGRAM_BOT_TOKEN` |
| **tw-stock-signal/** | 盤前 daily 訊號 + 三層基本面分析 + 量縮 vol_shrink | FinMind daily | 每天 07:00-08:00 跑一輪 | `TELEGRAM_BOT_TOKEN` |

**為什麼不合併**：
- FinMind 免費 tier 不支援分鐘 K（§3.1）→ tw-stock-signal 若改盤中即時必須換 Shioaji
- 但 Shioaji 即時 + N-Pattern watcher 已經在 backend/ 完整實作（§2.7.6）
- 合併 = 把 backend/ 已有的整套重寫一次到 tw-stock-signal/，純浪費工

**backend/ 盤中即時是 A+B+C 三件齊的完整證據**（2026-05-26 對話中逐行驗證）：
- A+B+C = 拉新大盤 / 拉新個股 / 重算 signal 並推播
- `smc_bot.py:749` `app.job_queue.run_repeating(_job_watcher, interval=180, first=30)` — 每 3 分鐘 cron
- `smc_bot.py:357-361` 時間閘：`weekday<5` AND `hour∈[9,14)`（盤後/週末跳過、不浪費 API）
- `_run_watcher_pass:321` `await gather_context(symbol)` 對 watchlist 每檔現拉
- `context.py:40` `_CACHE_TTL_SECONDS=30`（< cron 180s → 每輪都會重拉，不會吃過期 cache）
- `_run_watcher_pass:325-326` 跑 `evaluate_first_beat` / `evaluate_db_approach` / `evaluate_ob_formation` 三個 setup
- `:335` 推 Telegram，搭配 60 分鐘 `alert_state.should_push` dedup（防 FOMO 轟炸）
- `:369` 同輪順便跑 `sim_check_positions()` → stop/target 觸發自動結算 + 推播

**規則（未來新需求落腳處）**：
- 「盤中即時 / setup watcher / 即時推播」功能 → **加在 backend/**
- 「盤前 daily / 基本面 / chip 分析 / 量縮 vol_shrink」功能 → **加在 tw-stock-signal/**
- 共用：兩邊都用 `data/day_trade_watchlist.json`（當沖 watchlist），其他資料各自管理

**反 pattern（不要犯）**：
- ❌ 「在 tw-stock-signal 加盤中即時化」— 會撞 FinMind paywall + 重做 backend/ 已有的
- ❌ 「把 backend/ 的 N-Pattern watcher 搬到 tw-stock-signal」— 兩邊 bot token 不同、entry point 不同、會 409 Conflict

---

## 2.10 ⭐ 2026-06-03 — OBV × 籌碼集中度背離偵測 PoC【最新】

### 2.10.1 背景與架構決策

收到 master prompt 要做「OBV ↑ + 籌碼集中度 ↓」背離偵測（主力疑似出貨警示，純警示不下單），原規劃要做盤後 + 盤中兩種推播。

**架構決策**（依 §2.9 規則）：
- ✅ **只做盤後版**，放 `tw-stock-signal/`
- ❌ **盤中即時版降為 P2**（時間框架矛盾：集中度本質 T+1 才有，「昨日集中度 + 今日 OBV」訊號品質低）
- ❌ **不在 tw-stock-signal 接 Shioaji 即時**（撞 FinMind paywall §3.1 + 重做 backend/ 已有的 cron watcher）

### 2.10.2 ⚠️ 重要踩坑（會影響後續決策）

**坑 1：FinMind 免費 tier 不能當集中度資料源**
- `scrapers/finmind/shareholding.py` docstring 明寫：`TaiwanStockShareholding` 在免費 tier **沒有 `HoldingSharesLevel` / `HoldingSharesProportion` / `NumberOfShareholders`** → 拿不到大戶持股比例
- chip.py `_shareholding_stats` 拿到空 DataFrame 就回 `-1`、H5 自動豁免 → 現有系統根本沒在用真實大戶集中度
- **教訓**：以後新增任何依賴「真集中度」的策略不能假設 FinMind 給得了

**坑 2：HiStock 真正的集中度頁面 URL 是 `chartdata.aspx`，不是 `concentrate.aspx`**
- 試打 `https://histock.tw/stock/concentrate.aspx?no=2330` → 404
- 真正的 chip 頁是 `chips.aspx?no=2330`（HTML 127KB，含 Highcharts 內嵌資料）
- 但更乾淨的是 AJAX endpoint `chips.aspx` 內 line 890 引用的：
  ```
  https://histock.tw/stock/chip/chartdata.aspx?no={sid}&m={comma-separated-metrics}
  ```
- 直接回 JSON（44KB），不用爬 HTML

### 2.10.3 HiStock chartdata.aspx 介面實錄

**請求**（必要 headers）：
- `User-Agent`: 設一般瀏覽器即可
- `Referer`: `https://histock.tw/stock/chips.aspx?no={sid}`（保險加，未驗證沒加會不會被擋）
- `X-Requested-With`: `XMLHttpRequest`（AJAX 慣例）

**Metric keys**（可用 `m=` 逗號分隔組合）：
```
dailyk, Close, Volume,
mean5, mean10, mean20, mean60, mean120, mean240,
mean5volume, mean20volume,
broker1, broker3, broker5, broker10,   # 主力買賣超 (1/3/5/10 日)
chip1,   chip3,   chip5,   chip10,     # 籌碼差
focus1,  focus3,  focus5,  focus10     # 籌碼集中度 (1/3/5/10 日, %)
```

**Response 結構**：
```json
{
  "Close":   "[[unix_ms, price], ...]",   // capitalized!
  "Volume":  "[[unix_ms, lots], ...]",    // capitalized!
  "focus5":  "[[unix_ms, pct], ...]",     // lowercase!
  "focus10": "[[unix_ms, pct], ...]"
}
```
- ⚠️ key 大小寫不一致：`Close`/`Volume` 是 capitalize，`focus5` 等是 lowercase
- ⚠️ value 是 **JSON string**，要 `json.loads(d["focus5"])` 再次 parse（不是 nested array）
- 大約 250 個交易日歷史可拉，z-score 樣本充足

**HiStock 沒有 `focus20`** — PoC 用 `focus10` 代理 CONC_20，未來需要可從 `broker1` 自己 rolling 20。

### 2.10.4 PoC 指標公式（已實作）

```
OBV          = 標準累積 OBV from close + volume
OBV_smooth   = EMA(OBV, span=5)
CONC_5       = HiStock focus5 (5 日 rolling 主力買賣超 / 量, %)
CONC_smooth  = EMA(CONC_5, span=5)
OBV_slope    = linregress(最近 5 天 OBV_smooth).slope
CONC_slope   = linregress(最近 5 天 CONC_smooth).slope

歷史窗口 60-120 天：
  >= 60 → z-score
  <  60 → 百分位法 (排序中心化到 [-2, 2])

分級：
  weak    : OBV_z > 0    且 CONC_z < 0
  medium  : OBV_z > 0.5  且 CONC_z < -0.5
  strong  : OBV_z > 1.0  且 CONC_z < -1.0
  confirmed: 連續 K=2 天 >= medium
```

### 2.10.5 PoC 驗證結果（180 天歷史、2026-06-03 跑）

| 標的 | weak | medium | strong | confirmed(K=2) | total | 訊號率 / 月 |
|---|---|---|---|---|---|---|
| 2330 台積電 | 13 | 2 | 2 | **2** | 116 | ~0.4 次 |
| 2382 廣達 | 12 | 7 | 0 | **5** | 116 | ~1 次 |

- 訊號頻率落在合理區（不 spam、不死訊號），門檻先不調
- **2330 04-22~04-29 連續訊號**（04-24 medium）→ 5/04-5/22 OBV 持續下跌 → 事後看具預警價值
- 2382 訊號量多但無 strong，對應 §3.2「2382 整體期望值 -0.17」的波段不穩特性
- z-score 路徑全部啟用（前 60 筆走 percentile 退路、後 56 筆走 z-score）

### 2.10.6 新增檔案位置

```
tw-stock-signal/scrapers/concentration/__init__.py
tw-stock-signal/scrapers/concentration/base.py        # ConcentrationDataSource Protocol
tw-stock-signal/scrapers/concentration/histock.py     # HiStock JSON adapter
tw-stock-signal/strategy/obv_divergence.py            # OBV + 集中度 + z-score + 分級 + 確認
tw-stock-signal/scripts/probe_histock.py              # PoC HTML probe（已執行）
tw-stock-signal/scripts/probe_histock_api.py          # PoC JSON probe（已執行）
tw-stock-signal/scripts/poc_obv_divergence.py         # PoC 回測 script（已執行）
tw-stock-signal/scripts/poc_data/*.html / *.txt       # probe 留檔
```

**沒動的東西**：`backend/` 整個資料夾、`tw-stock-signal/` 既有檔案、DuckDB schema、Telegram bot、APScheduler。

### 2.10.7 下一步待做（按順序）

- [x] **Premium Zone 確認層** ✅ 2026-06-03 已實作於 `obv_divergence.py::_compute_price_zones`（rolling 20 日 close max/min 取中點，confirmed 訊號要求 `persist_flags AND zone == PREMIUM`）
- [x] **跨 7 檔批量驗證** ✅ 2026-06-04 完成（見 §2.10.9）— 結果 OK，可進下一階段
- [ ] **CONC_20 用 focus10 代理 vs 從 broker1 自己 rolling 20**：對比同期訊號差異
- [ ] **DuckDB 表 + APScheduler 14:45 cron + Telegram 推播**：批量驗證已過，可開始做

### 2.10.8 已決議不做的事

- ❌ HiStock 不寫 fallback adapter（PoC 一次就通、無付費需求、無反爬蟲）
- ❌ FinMind 不升付費 tier（拿到 `major_holder_ratio` 也只是另一種代理、不是真分點集中度）
- ❌ 盤中即時版不做（時間框架矛盾、§2.9 規則阻擋）

### 2.10.9 ⭐ 2026-06-04 — 跨 7 檔批量驗證結果

**目的**：驗證 §2.10.5 的「訊號頻率合理」是不是只在 2330/2382 成立（避免 PoC 過擬合 2 檔特例）。

**新檔案**：`tw-stock-signal/scripts/poc_obv_divergence_batch.py`
**輸出**：`tw-stock-signal/reports/obv_divergence_batch_20260604.csv`

**結果（180 天歷史）**：

| Symbol | weak | medium | strong | confirmed | confirmed/月 | LESSONS §3.2 WR |
|---|---|---|---|---|---|---|
| 2330 台積電 | 12 | 3 | 1 | 2 | 0.3 | 25.8% |
| 2317 鴻海 | 9 | 7 | 0 | 5 | 0.8 | 44.5%（最佳） |
| 2308 台達電 | 14 | 5 | 7 | **10** | **1.7** | 25.2% |
| 2382 廣達 | 11 | 6 | 0 | 4 | 0.7 | 7.7%（最差） |
| 2454 聯發科 | 10 | 3 | 4 | 4 | 0.7 | 42.4% |
| 2449 京元電子 | 7 | 3 | 2 | 2 | 0.3 | — |
| 3231 緯創 | 12 | 3 | 1 | 2 | 0.3 | — |

**4 個發現**：

1. ✅ **訊號率分布合理**（多數 0.3-0.8 次/月、無 spam、無死訊號）。Premium Zone gate 有效（所有 `last_zone=premium`，代表 Discount 區的背離都被擋住）
2. ⚠️ **2308 訊號量太多**（1.7 次/月、7 個 strong）→ 跟 §3.2「2308 R:R 29.43 但 WR 25.2%、停損太遠」可能同源（標的本身波動率特性 + 籌碼結構）。不一定是 indicator 問題、但**單一標的需要更高門檻或加上額外確認層**
3. ⭐ **2317 5/14-5/19 連續 4 天 confirmed、5/19 仍是 weak/premium**（最新狀態仍在發生）→ 過去 backtest WR 最佳的鴻海此刻疑似主力出貨、**未來 1-2 週可拿來事後驗證 indicator 是否真有預警價值**
4. 📍 **2026-04-17 → 04-21 群聚訊號**（2308/2382/3231 同時 confirmed）→ 大盤級事件、不是個股特性。indicator 對大盤級轉折有反應 = 良性訊號

**結論**：可以進下一階段（DuckDB 落地 + APScheduler 14:45 cron + Telegram 推播）。

**追蹤事項**：
- [ ] 約 2026-06-19（2317 訊號後 1 個月）回頭看 2317 股價走勢、驗證此次 confirmed 訊號是否有預警價值
- [ ] 2308 是否單獨調高門檻、或留作 indicator 自然頻率高的特例

---

## 2.11 ⭐ 2026-06-08 — 盤末漲幅榜推播（12:30/13:00/13:30）

**需求**：使用者要在 12:30 / 13:00 / 13:30 收到「今日漲幅 ≥ 5% 的股票」清單。

**架構決策**（依 §2.9）：盤中即時推播 → 加在 **`backend/`**（Shioaji + `SMC_TELEGRAM_BOT_TOKEN` + JobQueue）。
- 掃描範圍使用者選 **只上市 (TSE)**（不含上櫃）。
- 用 **`api.snapshots()` 批次抓即時報價**（不是逐檔 K 線）→ 只需 Data 權限、約 3 個 batch 跑完全上市，避開 §3.8 連線累積。
- 過濾普通股：`code` 4 碼純數字且首碼非 0（排除 ETF 00xx / 權證 6 碼 / 特別股帶字母）。
- 假日防呆：snapshot 全市場 `total_volume==0` → `market_active=False` → 不推誤導訊息。

**新增/改動**：
- `shioaji_fetcher.py`：`shioaji_scan_gainers()` + `Gainer`/`GainerScan` dataclass + `_sync_scan_gainers` / `_tse_common_contracts`
- `smc_bot.py`：`_job_gainers` / `_format_gainers` + `/gainers` 手動指令 + 3 個 `run_daily`（台北時間，weekday guard 在 callback 內）

**⚠️ 與 §2.7.4c FOMO 原則的張力**：這是「全市場掃描」，違反「只看 watchlist」。**合理化理由**：12:30+ N 字進場窗口（09:30-12:30）已過，此清單定位為**盤末強勢股回顧 → 明日備課素材**，非當下追高訊號。未來若發現使用者拿它盤中追價，需重新評估。

**踩到的環境坑（重要、會影響下次）**：
1. **專案實際 interpreter = global Python 3.13**（`C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe`，裝有 pandas / shioaji 1.3.3 / python-telegram-bot 22.7）。**專案根 `venv/` 是空殼，別用**（會 `ModuleNotFoundError: pandas`）。
2. **Shioaji 登入會被 IP 白名單擋**：2026-06-08 首次實測回 `{'status_code':400, ... 'detail':'ip: <IP> not allow.'}`。換機器 / 動態 IP 變動後，必須先到永豐 API 後台把新 IP 加白名單，否則 bot 所有 Shioaji 抓資料都會失敗。→ **換新 key 後同日已實連驗證通過**：1082 檔上市普通股、`change_rate` 確認是百分比（門檻 5.0=5% 正確）、當日掃到 24 檔漲 ≥5%（和桐/嘉聯益 +10% 漲停等、股名正確解析）。
3. **既有 PII log 洩漏**（非本次引入、暫不修）：`shioaji_fetcher._get_api()` 的 `logger.warning("Shioaji login failed: %s", exc)` 會把 shioaji 原始例外（含 `person_id` 身分證號 + IP）印到 server log。§3.7 的濾鏡只擋 Telegram，沒擋 log。要修的話 login except 也該套 `_sanitize` 類過濾。

**部署 / 啟動（2026-06-08 釐清，重要）**：
- **smc_bot 啟動方式 = `python -m backend.smc_bot`**（用 global Python 3.13）。新增 `啟動SMC機器人.bat`（雙擊即可，崩潰自動 5 秒重啟，log 寫到 `%TEMP%\smc_bot.log`）。**這支之前沒 auto-restart**，§3.8 SIGSEGV 崩了就沒了 → 使用者「看不到指令」常是因為 smc_bot 根本沒在跑。
- **⚠️ 兩支 bot 別搞混**（接續 §2.9）：`/gainers` 等盤中指令在 **smc_bot**（`SMC_TELEGRAM_BOT_TOKEN`，是 Telegram 上**另一支** bot）；每天 07:00 盤前報告那支是 `tw-stock-signal/main.py --daemon`（`TELEGRAM_BOT_TOKEN`，由 `start_daemon.bat` 跑）。使用者要在「SMC 那支 bot 的對話」裡才看得到 `/gainers`。兩支 token 不同所以可並存（同 token 才 409）。
- **.bat 坑**：cmd `.bat` 裡放太多中文 echo 行會卡住解析、走不到 python 那行（python 進程根本沒生出來）。修法：`.bat` 內容盡量 ASCII + `chcp 65001`，python 輸出用 `>> "%TEMP%\smc_bot.log" 2>&1` 導出（視窗留給使用者、log 留給除錯）。

---

## 2.12 ⭐ 2026-06-09 — `/scan` 當沖選股篩選器（交易紀律程式化）

**需求**：使用者給一套當沖進場紀律，要寫進 Telegram bot。**決策（AskUserQuestion）**：範圍＝客觀篩選 + 量化型態；量能基準＝前 20 日均量 ×1.5。

**實作**：`backend/momentum_scan.py`（純函式 + dataclass）+ smc_bot `/scan`。

| 紀律 | 實作 | 類型 |
|---|---|---|
| 1 大盤環境 | 全股 snapshot 算上漲家數占比 breadth（≥50%偏多 / <40%偏空），不另抓指數 | soft（偏空標⚠️不硬擋）|
| 2 漲幅≥5% | snapshot change_rate ≥ 5 | 硬篩 |
| 3 均線多頭未發散 | 日 MA5≥MA10≥MA20≥MA60 且 (close-MA20)/MA20 ≤ 12% | 硬篩 |
| 4 量能 | 今日量 ≥ 前20日均量 ×1.5 | 硬篩 |
| 三角收斂/盤整 | 均線帶寬/MA20 ≤5%(糾結) + ATR5<ATR20(波動收縮) | 加分 |
| 區間突破 | close > 前20日最高 | 加分 |
| 月/週/日 | 日線 resample 週(MA5/20)/月(MA3/6) 各報多頭/盤整/空頭 | 顯示+加分 |

型態分 0–5 = 糾結+收縮+破20日高+週多頭+月多頭，依分排序。

**⚠️ 刻意不做**：杯柄/嚴格三角等**圖形辨識不自動做**（主觀易誤判，非技術使用者會誤信 → §2.7.4c「紀律外包給 bot」風險）。只給可量化近似 + 三週期狀態，圖形留使用者人工判。要加圖形辨識前先想清楚誤判責任。

**驗證（2026-06-09 實連，06-08 收盤資料）**：掃 1082、漲87/跌970→偏空、漲幅≥5% 24 檔→過四關 1 檔（6153 嘉聯益 +10% 量4.3× 月週日全多頭）。有鑑別力、不照單全收。

**效能/調參**：snapshot 全市場 + 漲幅前 40 檔(`DEEP_LIMIT`)逐檔日線(260 根)，~30-40s，在 thread 跑不阻塞。門檻常數全在 `momentum_scan.py` 頂部（`MIN_CHANGE_PCT`/`VOL_MULT`/`MA_CONVERGED_MAX`/`EXTEND_MAX`/`BREAKOUT_LOOKBACK`/`BREADTH_*`）。

**量單位確認**：日線 K 棒 volume 與 snapshot total_volume 同單位（張），量能比可直接算（2330 兩者皆 ~44,000 驗證）。

---

## 2.13 ⭐ 2026-06-10 — 鑽豹評鑒 + 本益比合理價 + 拉回整理檢查（三合一研究工具）

**需求**：使用者要 (a) 鑽豹評鑒（財報 6 面向 15 分、高分自動記錄）(b) 合理股價=預估EPS×本益比 (c) 拉回整理股篩選（週/月線、離高點有距離）。全部進 smc_bot。

**新模組**：`backend/diamond_score.py` / `pe_valuation.py` / `pullback_check.py`；指令 `/dia [codes]`（無參數=看記錄）/ `/pe code [自估EPS]` / `/pullback [codes]`（無參數=鑽豹記錄+watchlist）。

**鑽豹計分（15 = 3+2×6）**：營收3（月YoY>0／近3月累計YoY>10%／創12月新高）；毛利率2、營業利益率2、EBITDA率2（各 QoQ↑/YoY↑）；存貨2（QoQ↓／存貨YoY<營收YoY）；合約負債2（恆 0，見下）；FCF2（最新季>0／近4季累計>0）。≥10 分自動記 `data/diamond_picks.json`（原子寫入、同 code 覆蓋）。

**⚠️ 資料源限制（已實測確認）**：
1. **FinMind 免費版資產負債表沒有合約負債**（101 個 type 全列過，無 Contract/預收類）→ 該項恆 0 分、訊息標「無資料」。實際滿分 13。
2. **TaiwanStockPER 全市場單日查詢=付費牆** → 產業中位 PE 無法自動算（逐檔拉同業會爆免費額度）。`/pe` 改用個股自身 5 年 PE P25/P50/P75 當保守/合理/樂觀，產業欄只顯示分類名。
3. **TaiwanStockInfo 一檔可能多個產業分類**（2330＝電子工業+半導體業）。

**⚠️ 最重要的坑：現金流量表是「年內累計制」**（Q2=上半年累計、Q4=全年累計、隔年 Q1 重置；2330 實測確認）。直接拿 row 加總/比較會嚴重失真（修正前 2330「近4季FCF」算出 24,793,261 億的笑話）。修法：`diamond_score._decum()` 同年內後季減前季還原單季。**損益表(TaiwanStockFinancialStatements)是單季值**（EPS TTM=74.39 與台積電真實值吻合驗證）、資產負債表是時點值，都不用 decum。**現金流量表單位=元**（非千元；2330 全年 OCF 2.27 兆驗證）→ 億 = /1e8。

**拉回整理判定**（`pullback_check.py` 常數可調）：距 52 週高回檔 15–50% + 月線趨勢在（月MA6 上揚或價>月MA12）+ 近 4 週週K區間 ≤12%（整理中），三條全過=✅候選。Shioaji 日線 400 根。

**驗證（2026-06-10 實測）**：2330 鑽豹 11/15（FCF 10,560 億 ✓ 符合真實量級）；/pe 2330：5 年 PE 16.7/23.4/27.5、EPS(TTM)74.39、合理價 1243/1738/2046 vs 現價 2305（+33% 高於 P50）；/pullback：2330 距高僅 5.5% 不是候選 ✓ 邏輯正確。

**附帶安全修補**：httpx 每 10 秒把含 bot token 的 getUpdates URL 用 INFO 寫進 `%TEMP%\smc_bot.log` → smc_bot 加 `logging.getLogger("httpx").setLevel(WARNING)` 關掉（§3.7 精神延伸：log 也不留 token）。

---

## 2.14 ⭐ 2026-06-11 — ATM Model × N 字 合併策略 + 生圖工具

**來源**：使用者看 YouTube ATM Model 影片（亞洲盤交易策略，用 NotebookLM 讀字幕），要把它跟 N 字戰法合併、並做「個股 K 線疊策略標記」生圖。

**決策（AskUserQuestion）**：
- 整合範圍 = **只寫策略文件，不改訊號程式**（模擬/實盤期謹慎）
- 生圖形式 = **真實個股 K 線疊 ATM×SMC 標記**（輸出 PNG，適合 Telegram/聊天框）

**關鍵洞察**：ATM 跟你的 `n_pattern.py` 是同骨架（H1/L1 時段高低 + OB 回踩 + 停損掛 OB 外緣都已有）。ATM 真正補的 3 件：① **收針（影線拒絕）當硬門檻** ② **反轉型**備援 ③ **1:3 目標**（你目前 target=H1 保守）。

**TWSE 適配坑**：ATM 原始時段（亞洲盤 06–07 / 東京盤 09–10 GMT+8）是給 24h 市場（NQ/加密貨幣）。台股 09:00 才開盤、沒盤前窗口 → 合併版 TWSE 改用**開盤段 09:00–09:30** 當「時段高低」。別跨品種硬套時段。

**產出**：
- `ATM_SMC_策略.md`（完整合併規格 + 第 5 節「生圖視覺規格」）
- `backend/strategy_chart.py`（K 線疊策略標記 → PNG；CLI `python -m backend.strategy_chart <symbol>`；`--demo` 離線測試）
  - 純繪圖 `_draw_figure` / `render_strategy_chart`(存檔) / `build_chart_png`(回 bytes) / `generate_chart_png`(高階 async，給 bot)
  - 資料：今日用 `gather_context` 真實 OB；指定日用 `shioaji_fetch_m3`；只畫**單一交易日盤中 M3**（當沖定位）
  - 台股慣例紅漲綠跌；繁中字型 `Microsoft JhengHei`（避免 ✓/⚠ 等缺字 glyph 變豆腐）
- **Telegram `/chart 2330 [YYYY-MM-DD]`**（smc_bot `cmd_chart` + 註冊；繪圖丟 `asyncio.to_thread` 不卡 bot；錯誤走 `_safe_err`）。**需重啟 bot 才生效**（雙擊 `啟動SMC機器人.bat`）。
  - ⚠️ 第一版漏加進 `_post_init` 的 `set_my_commands` 清單 → Telegram 選單看不到。**新指令一定要兩處都加**：`add_handler`（能執行）+ `set_my_commands` BotCommand（選單看得到）。
  - 無參數 `/chart` = 畫 watchlist 首檔（符合 §2.7.5「選單點一下就有東西」原則）；要指定檔打 `/chart 2330`。
  - ⚠️ **重啟踩坑（2026-06-11）**：使用者關掉舊 bot 視窗後，新的雙擊沒成功開起來 → 變成 0 個 bot 在跑、所有指令「沒連到」。**驗證重啟成功的方法**：(a) `Select-String %TEMP%\smc_bot.log 'registered \d+ telegram bot commands'` 最後一行要是**今天時間戳 + 正確指令數**；(b) `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 要剛好 **1 個**（0=沒跑、2=409 衝突）。bot 解譯器 = `Python313\python.exe`（**3.13.13**，與 shell 的 3.14 不同！），已確認有 mplfinance/matplotlib。

**待驗證（落地前）**：收針門檻要先在 N 字 backtest 加過濾測勝率（≥90 天，§2.8 教訓）；反轉型本質逆勢、跟 §2.5 禁 Premium Fade 同性質 → 先紙上模擬。**本次未改任何訊號程式（僅加唯讀生圖指令）。**

---

## 3. 踩過的坑（不要再犯）

### 3.1 FinMind 免費 tier 不支援分鐘級 K
- **症狀**：呼叫 `TaiwanStockKBar` 回 400 + `"level is register"` / `"update your user level"`
- **處理**：實作 `FinMindPaywallError` typed exception，偵測到 paywall **不重試**，並標記全域 `_intraday_paywalled`，自動 fallback 到日線
- **行動**：要分鐘線必須付費 tier，或改用 Shioaji（目前已採用）

### 3.2 ⚠️ 同一套 SMC pipeline 在不同股票表現差異極大（最重要！）

從 `reports/smc_backtest_*_summary.txt`（30 天回測）：

| 股票 | 整體勝率 | 期望值 R/signal | 重點觀察 |
|------|---------|----------------|---------|
| 2317 鴻海 | 44.5% | +0.97 | Unicorn 92.9% (13W/14) 王者 |
| 2454 聯發科 | 42.4% | +0.69 | Breaker 80%、Mitigation 56%、OB 54.5% |
| 2308 台達電 | 25.2% | +0.86 | R:R 29.43 但勝率低，停損太遠 |
| 2330 台積電 | 25.8% | +0.02 | 邊緣正期望，只有 OB 38% 撐住 |
| 2382 廣達 | 7.7% | **-0.17** | **所有 setup 失敗** |

**教訓**：絕對不能用同一份 setup config 跑所有股票。**已於 2026-05-16 決議：題材白名單 + per-symbol direction，參見 2.2 / 2.3。**

### 3.3 Premium Fade 跨股票全 0% 勝率
- **資料**：2330 / 2317 / 2382 / 2454 共觸發約 50 次，**全部失敗**
- **✅ 已於 2026-05-16 決議：直接禁用，參見 2.5**

### 3.4 Unicorn (Breaker × FVG) 對股性極度敏感
- **2317 鴻海**：92.9% 勝率（14 次觸發 13 勝）
- **2382 廣達**：4.3%（24 次觸發只贏 1 次）
- **2454 聯發科**：66.7%（3 次）
- **2308 台達電**：0%（10 次全敗）
- **教訓**：高勝率的 setup 不代表全局可用，必須先驗證標的相容性。題材白名單機制（2.2）落地後可自然解決。

### 3.5 avg R:R 過高反而是停損過遠的警訊（不是越大越好）
- **2308**：R:R 29.43 但勝率 25.2%
- **2382 OB Retest**：R:R 22.12 但勝率 12.7%
- **BTC M1 全 7 setup**：avgR:R 32.00 整體 WR 13.8%（§2.8.3）
- **BTC M15 180d 整體**：avgR:R 19.68 看似 EV+0.44R 但 WR 只 17.1%（§2.8.4）
- **道理**：R:R > 10 通常代表停損點離進場太遠（或更糟，**stop 跟 entry 重疊**），每次贏雖然抵很多次輸，但勝率支撐不住
- **新發現（2026-05-17）**：在 crypto 上，R:R > 10 不只是「停損過遠」還可能是「停損和進場錯位」— 例：OB Retest 偵測到 FVG 時 entry 改成 FVG 中點，但 stop 仍錨定 OB 底，若 FVG 中點落在 OB 下方則 stop > entry on long → 即時 loss（§2.8.6）
- **行動**：把 R:R > 10 的訊號當作「進場品質有問題」來檢視，不是當作好訊號。整體 backtest 看到 avgR:R > 10 時要懷疑「正 EV 是不是數學魔術」

### 3.6 回測 open（未結算）比例過高 → 評估失準
- **2330**：18/49 = 37% 未結算
- **2308**：54/209 = 26% 未結算
- **問題**：未結算單沒算進勝率，數字會樂觀
- **行動**：拉長回測週期，或強制以最後一根 K 線收盤價了結未結算單

### 3.7 ⚠️ Telegram bot 把 raw exception 推給使用者會洩漏 secret【2026-05-20 安全事件】
- **情況**：`cmd_scan` 對 shioaji exception 用 `f"日線拉失敗（{exc}）"` 直接推到 Telegram
- **問題**：shioaji exception 把 request payload 完整 dump，含 **完整 JWT token + person_id + IP + PYAPI client string**
- **後果**：token 留在 Telegram 雲端 + 截圖貼到外部對話 → 12 小時內外洩
- **這次運氣**：洩漏的 key 只有 `permissions: ["Data"]`，不能下單；但若是含「交易」權限的 key 就完蛋
- **修補**（commit 2026-05-20）：
  - `backend/smc_bot.py::_safe_err()`：所有 cmd handler 推 exception 前先過濾 JWT / API key / `'token': ...` / PYAPI client / 身分證號（[A-Z]\d{9}）/ 長 base64
  - 5 處 cmd handler 改用 `_safe_err()`：cmd_scan / cmd_aistockmap / cmd_analyst_scan / cmd_ai_analyse / cmd_overnight_check
- **教訓**：**永遠不要把 raw exception 直接送 Telegram / Web / 任何公開介面**。三方 lib（shioaji / FinMind / pysolace）的 exception 經常把 request payload 整段塞進 message，無法控制 lib 端 logger
- **永久措施**：新 cmd handler 一律用 `_safe_err(exc)` 包過 exception；任何要送 Telegram 的字串都過 `_sanitize_for_telegram()`

### 3.8 ⚠️ Shioaji reset_login 必須先 api.logout()，否則累積 451 + native SIGSEGV【2026-05-20】
- **症狀**：bot 跑 19 分鐘到 5 小時不等，會出現 `status_code: 451 Too Many Connections.`，之後 shioaji native lib `pysolace` 進入「Not ready」狀態反覆 retry → SIGSEGV (exit 139)
- **根因**：原本 `reset_login()` 只清 Python 端 `_api = None`，shioaji server 那邊還記得這條 session 佔著連線額度
- **累積路徑**：每次 token 過期 → reset_login → 又留一條殭屍 session；多次後撞單帳號連線上限
- **加上跑 demo script**（`demo_ai_report_real` / `screenshot_*` 等）也會各自建 session 不 logout，更快累積
- **修補**（commit 2026-05-20）：
  - `backend/shioaji_fetcher.py::reset_login()`：先 best-effort `old_api.logout()`，再清 `_api = None`
  - 加 `@atexit.register` 確保 process 正常結束時 logout
- **教訓**：lib 釋放資源時，**Python 端清狀態 ≠ server 端清連線**。任何「自動 retry + 累積式」的 lib 都要顯式呼叫 logout / close / disconnect
- **未做**：SIGSEGV 是 native crash，atexit / Python signal handler 都接不到 → 未來加 process supervisor（subprocess watchdog 或 Windows scheduled task auto-restart）

### 3.9 ⚠️ tw-stock-signal `_analyze_one` 對大盤指數 N+1 query【2026-05-26】
- **症狀**：`scheduler/daily_job.py::_do_analyze` 對 ~1700 檔股票 dispatch `_analyze_one`，每檔都呼叫 `read_market_index(days=10)` 讀同一份 TAIEX 大盤資料
- **規模**：1,700 次重複 DuckDB query + 1,700 次 connection open/close，純粹浪費（大盤指數對所有 symbol 都一樣）
- **修補**（2026-05-26）：
  - `_analyze_one` 簽名加 `market_idx: pd.DataFrame` 參數（`daily_job.py:141`）
  - 由 caller 在 dispatch 前讀一次傳進去：`_do_analyze` (`daily_job.py:254`) 與 `bot_handler._run_analyze_from_db` (`bot_handler.py:415`) 兩處都改
  - `bot_handler.py` lazy import 加 `read_market_index`
- **未做（待 B/C 修補）**：`_analyze_one` 內還有 4 個 per-symbol read（prices / institutional / margin / shareholding），每個都自開新 DuckDB connection。理論上可改成「整檔共用一條 conn 跑 4 個 SELECT」進一步省 6,800 次 connection open——但需要改 `store.py` API（讓 caller 傳入 conn 而不是每次自開），影響面較大，暫不做
- **教訓**：dispatch 給 N 個 task 前，凡是「整批共用 / 不隨 symbol 變動」的資料一律提到 dispatch 外面預讀。typed 簽名（強制傳參）是 enforce 這點的最好工具——比口頭約定可靠

---

## 4. 待驗證 / 未決議

- [ ] **A1 的 63.9% 勝率對應的 backtest summary 在哪？** 目前 `reports/` 看不到，需重跑或補存
- [ ] **C7d Order Block 過濾要不要也套到其他 setup**（不只 A1）？尤其是表現差的 Breaker、Mitigation
- [ ] **2382 廣達為什麼整體 -0.17**？已於 2.3 決議處理方式，但根本原因（基本面驅動 / 籌碼集中 / 波動率特性）還沒實證
- [x] **`aistockmap.com` 評估** ✅ 2026-05-16 晚間：可用，Playwright 抓 daily 分頁 6-7 條焦點，更新時間每日 12:00（台灣），個股大多 Premium 鎖定
- [ ] **熱度指標資料源**：⚠️ 當沖定位後此項降級（時間框架不對）
- [ ] **N 字戰法時框**：M3 / M5 / M3+M5 雙確認 哪個訊號品質最好？（§2.7.5 Q3）
- [ ] **隔日沖判斷閾值**：「前日 > X% + 今日開高 > Y%」最佳 X/Y 組合需回測（§2.7.5 Q2）
- [ ] **Premium Fade 在當沖時段（09:30-12:30）是否仍應禁用？** §2.5 禁用決策是波段視角，當沖視角需重測

---

## 5. 環境 / 工具備忘

| 項目 | 內容 |
|------|------|
| 即時資料源 | Shioaji（M3 真實，09:00–13:35 盤中掃描） |
| Crypto 資料源 | Binance public OHLCV via ccxt（`backend/crypto_data.py`，無需 API key） |
| 日線資料源 | FinMind（免費 tier 可用，分鐘線需付費） |
| 回測腳本 (TWSE) | `run_30day_backtest.py` |
| 回測腳本 (Crypto) | `run_btc_backtest.py` / `scripts/run_btc_mtf.py`（後者支援 5m/15m/30m/1h） |
| Crypto backtest 速度 | 53x 加速後，30 天 1m = 6 分鐘；180 天 15m = 21 分鐘 |
| 回測輸出 | `reports/smc_backtest_<symbol>_summary.txt` + `.csv` |
| SMC pipeline | `backend/smc_analyst/setups/*.py`（純函式） |
| HTML 報告 | `backend/smc_report.py` |
| Telegram 推播 | `backend/smc_bot.py` |
| Setup 掃描器 | `backend/scanner_a1.py` / `scanner_a2.py` |
| NO TRADE 守門 | `backend/no_trade_guard.py`（8 條硬性規則） |
| 雷老闆參考資料 | `雷老闆1.txt`（逐字稿）/ `雷老闆2.txt`（章節摘要） |
| aistockmap 爬蟲 | `backend/aistockmap_scraper.py`（Playwright，daily 分頁焦點題材） |
| 雷老闆 A/B 過濾 | `backend/theme_filter.py`（5 類關鍵字：缺貨/大客戶/新產品/新政策/新技術） |
| aistockmap HTML 報告 | `backend/aistockmap_report.py` |
| 當沖 watchlist | `backend/watchlist.py` → `data/day_trade_watchlist.json`（frozen dataclass + 原子寫入） |
| 隔日沖偵測（簡化版） | `backend/overnight_holders.py`（門檻：前日 >5% + 今開 >2%） |
| N 字 setup | `backend/smc_analyst/setups/n_pattern.py`（M3，Beat 1/2/3 + DB） |
| N 字先行警示 | `backend/n_pattern_watcher.py`（first_beat + db_approach，pre-trigger） |
| OB 形成警示 | `backend/ob_watcher.py`（最後 6 根 LTF 內新形成的 Bull/Bear OB → Telegram） |
| 警示去重 | `backend/alert_state.py` → `data/alert_state.json`（持久化 dedup） |
| AI 趨勢分析報告 | `backend/ai_analysis_*.py` + `scripts/demo_ai_report*.py`（5 維度評分 + 雙 K 線 + 可展開明細） |
| AI 評分 5 維度 | 籌碼 45%（FinMind 三大法人）/ 技術 35%（SMC 7-setup）/ 新聞 20%（aistockmap）/ 基本面、題材面 = 參考 |
| 盤前簡報 script | `scripts/aistockmap_brief.py --slot=morning\|evening`（獨立進程，配 schtasks） |
| Telegram 指令 | `/aistockmap` / `/wl` / `/wl_add` / `/wl_del` / `/wl_clear` / `/overnight_check` / `/analyst_scan` / `/watch_alerts` / `/ai_analyse` / `/smc_scan` / `/gainers`（盤末漲幅榜，§2.11）/ `/scan`（當沖選股篩選，§2.12）/ `/dia`（鑽豹評鑒）/ `/pe`（合理價）/ `/pullback`（拉回整理，§2.13）/ `/chart`（ATM×SMC 策略圖，§2.14） |
| Telegram 自動 cron | bot 啟動即排 `JobQueue.run_repeating(180s)` 跑 N 字 + OB watcher（盤中才動作）＋ `run_daily` 12:30/13:00/13:30 推上市漲幅 ≥5% 榜（§2.11） |
| Python interpreter | **global Python 3.13**（`...\Programs\Python\Python313\python.exe`，有 pandas/shioaji/PTB）；專案根 `venv/` 是空殼別用（§2.11） |
| Shioaji IP 白名單 | 登入被 `ip ... not allow` 擋時 → 永豐 API 後台加新 IP（換機 / 動態 IP 必踩，§2.11） |
| smc_bot 啟動 | 雙擊 `啟動SMC機器人.bat`（= `python -m backend.smc_bot`，自動重啟，log→`%TEMP%\smc_bot.log`）。盤中指令在這支（`SMC_TELEGRAM_BOT_TOKEN`），跟盤前 `tw-stock-signal` daemon 是不同 bot（§2.11） |
| Telegram bot token | **兩組分開**：`SMC_TELEGRAM_BOT_TOKEN`（這套 smc_bot 專用）+ `TELEGRAM_BOT_TOKEN`（給 `tw-stock-signal/main.py --daemon` 用），同 token 會 409 Conflict |
| Telegram 安全濾鏡 | `backend/smc_bot.py::_safe_err()` + `_sanitize_for_telegram()` — 所有 exception 推 Telegram 前過濾 JWT/API key/身分證/PYAPI client（§3.7） |
| Shioaji session 管理 | `reset_login()` 先 `api.logout()` 再清 Python 端 + atexit hook（§3.8 防 451/SIGSEGV） |
| 探勘工具（保留備用）| `scripts/probe_aistockmap.py` / `probe_focus_dom.py` |

---

## 6. 怎麼維護這份檔案

**Claude 行為**：
1. 每次新對話開始前先 Read 這個檔案
2. 完成回測 / 修策略 / 踩坑後，**直接更新**（使用者 2026-05-20 明示「以後不用問我了，想記就記」）
3. 不要把這份檔案塞滿瑣碎細節，只記**會影響下次決策**的事
4. 章節編號穩定，新內容優先放在「第 2 節 最新決策」下面用日期區隔
5. 更新後在回覆中提一句「已記入 LESSONS §X.Y」即可，不要長篇解釋

**使用者操作**：
- 「把 XX 記到 LESSONS.md」→ Claude 直接 Edit
- 「LESSONS.md 第 N 點過時了」→ Claude 直接刪除或標記
- 想看目前的策略事實 → 直接打開這個檔案讀
