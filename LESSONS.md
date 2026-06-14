# SMC 系統 — LESSONS 教訓記錄

> 跨對話的「策略決策 / 踩過的坑 / 待驗證事項」彙整。
> Claude 每次開新對話前必須先讀這份檔案，避免重複踩坑、保留前後文。
> 使用者要更新只要說：「把 OOO 記到 LESSONS.md」。

**最後更新**：2026-05-17（凌晨 — Crypto SMC 跨樣本驗證，發現 N-Pattern 是唯一可信 setup）
**對應 git commit**：**04b5a38**（feat: 當沖系統第一版閉環）+ backtest 優化 + crypto 驗證未提交

---

## 1. 程式碼 / 工程決策

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

---

## 2. ⭐ 2026-05-16 — 雷老闆面談後的策略升級【最新、最重要】

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

## 2.8 ⭐ 2026-06-14 — 雷老闆波段投資金律（書摘小筆記框）

### 2.8.1 六條金律原文

| # | 金律 | 程式對應狀態 |
|---|------|------------|
| 1 | 想賺 50–100% 的波段漲幅，約需 **1–3 個月** | — 持倉週期設定，當沖系統不適用 |
| 2 | **本益比 10–15 倍**是很好的介入點，長線漲幅可達 50% 以上 | ❌ 缺貨雷達尚未加 P/E 過濾 |
| 3 | 全世界只有台股每月公布營收，掌握「**營收帶動股**」| ✅ 缺貨雷達 Phase 1 月營收 YoY |
| 4 | 景氣好：**存貨增加是加分**；景氣下滑：存貨變扣分 | ❌ 缺貨雷達尚未看存貨週轉 |
| 5 | **合約負債 ≈ 股本 5% 或月營收 2 倍**，就值得研究 | ⚠️ Phase 2 有合約負債 YoY，但未設絕對量閾值 |
| 6 | 大猩猩選股法四大特徵：**新大客戶、新市場、新商業模式、新政策** | — 題材面，aistockmap 已接入 |

### 2.8.2 缺口待辦（依優先序）

1. **本益比過濾**（金律 2）：Phase 2 增益時加 P/E 10–15 倍判斷
   - 資料來源：FinMind `TaiwanStockPER` 或月 EPS × 12 估算
   - 行為：P/E < 10 → 超便宜加分；P/E > 25 → 估值偏高警告

2. **存貨週轉信號**（金律 4）：景氣判斷維度
   - 資料來源：Balance Sheet `Inventories` 欄位
   - 邏輯：存貨 YoY 上升 + 營收 YoY 上升 = 健康備貨（加分）
   - 邏輯：存貨 YoY 上升 + 營收 YoY 下滑 = 塞貨地雷（扣分 -1）

3. **合約負債絕對量門檻**（金律 5 精確版）：
   - 現有：YoY 增幅 > 40% → 標記 strong
   - 補：同時要求 合約負債 ÷ 最近月營收 ≥ 1.5 倍，才真的「值得研究」

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
| Telegram 指令 | `/aistockmap` / `/wl` / `/wl_add` / `/wl_del` / `/wl_clear` / `/overnight_check` / `/analyst_scan` / `/watch_alerts` / `/ai_analyse` / `/smc_scan` |
| Telegram 自動 cron | bot 啟動即排 `JobQueue.run_repeating(180s)` 跑 N 字 + OB watcher（盤中才動作） |
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
