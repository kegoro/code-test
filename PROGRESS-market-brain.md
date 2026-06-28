# PROGRESS — 跨市場「頂級腦袋」升級(market-brain)

**最後更新**:2026-06-15

> 跨對話進度記憶。新對話說「**繼續市場大腦**」→ 先讀本檔再接手。
> 規則/判斷依據在 `LESSONS.md` + `雷老闆第二大腦/`;本檔只記進度/狀態/計畫。

## 願景(使用者 2026-06-15)
做到「市面上頂級腦袋」等級:**雷老闆產業邏輯 + 真實財報/合約負債**,結合**台股/美股/日股**,並用**真實漲停/熱門族群數據判斷市場在瘋什麼**,不盲目、用數據說話。

## ⚠️ 誠實天花板(關鍵決策,不可畫餅)
- 頂級工具(彭博/FactSet)靠**付費數據庫**;我們用免費源,天花板在覆蓋度。
- **台股**:✅ 最完整(MOPS 官方,含合約負債/存貨)
- **美股**:🟡 堪用(yfinance 基本面+價格;合約負債 deferred revenue 要 SEC EDGAR XBRL,額外工程)
- **日股**:🔴 性價比最低(yfinance 財報覆蓋差、合約負債要 EDINET 日文 XBRL)→ **暫緩**,要做得花錢買數據(如 J-Quants 付費)

## 階段進度
| 階段 | 內容 | 狀態 |
|---|---|---|
| **1** | 台股熱門族群雷達(真實漲幅榜→族群排行→最熱族群跑四刀) | ✅ **完成 2026-06-15** |
| **2** | 美股四刀(yfinance 基本面+價格 + SEC EDGAR 合約負債) | ✅ **完成 2026-06-16** |
| 3 | 日股 | 🔴 暫緩(免費源差,需付費數據) |

## 階段1 已完成(`backend/hot_sector.py`)
- 資料源:Shioaji 漲幅榜(`shioaji_fetcher._sync_scan_gainers`) + `data/stock_industry.json`(TWSE 產業別,3101檔)
- 流程:抓今日強勢股(漲≥5%)→ 歸 TWSE 產業別 → 族群排行(強勢股數+均漲幅)→ 最熱族群前4檔跑基本面(第二刀 `_grade_second` + 第一刀 `diamond_blade1`)
- smc_bot:指令 `/hot` + 排程 `hot-sector-daily` 每日盤後 **14:00**(週一~五)
- 限制:族群=TWSE 產業別(粗,細題材 CPO/ASIC 需題材爬蟲);交易日才有資料;MOPS 限流時標「財報暫無」
- 驗證:周末用假漲幅數據(mock `_sync_scan_gainers`)測族群排行邏輯正確;`mf.fetch` 單獨驗證正常(限流是連續測試所致)

## 階段2 已完成(美股四刀)2026-06-16
- **`backend/us_fundamentals.py`(新)**:yfinance income_stmt/balance_sheet/cashflow → 六大指標(單位:百萬美元);回傳與 `mops_fundamentals.YearMetrics` 相容,直接餵 `diamond_full`。
- **合約負債**:先試 yfinance Deferred Revenue,不足→ SEC EDGAR `companyfacts`(XBRL `ContractWithCustomerLiabilityCurrent`,只取 10-K/FY)。VSH 實測抓到 $96M→$97M ✅。
- **第一刀/第三刀技術面**:`diamond_blade3._fetch_daily` 對英文 ticker 改抓 yfinance 日K 並映射成 FinMind schema → 兩刀零改動自動支援美股。
- **`diamond_full.analyze`**:`_is_us()`(含字母=美股)分流財報來源+顯示單位(`usd()` $B/$M vs 台股億元);`_grade_second(rows, money=...)` 參數化合約負債單位。
- **`/fin AAPL`**:`cmd_fin` 本來就原樣傳 token(只 `cmd_fin_zh` 過濾數字),故美股免改指令。VSH 完整四刀實測通過。
- 環境:yfinance 1.3.0 已裝。SEC UA 用 `SEC_CONTACT` env(預設佔位 email,無個資硬編)。
- **未做**:美股熱門族群(無漲停制度,要接 screener/漲幅異動榜)— 留待階段2.5。
- 首批可驗證:VSH(已測)、NVDA、AVGO、MRVL、COHR、LITE、ANET。

## 階段2 加強(2026-06-16 下午)
- **財報改季度**:`us_fundamentals.fetch(period='quarter')`,顯示日曆季標籤(2025Q1…2026Q1)。
  - yfinance 免費季報只回最近 ~7 季,且部分季營收 NaN → 實際乾淨約 5 季(如 AMD/IREN 給 2025Q1~2026Q1)。要 2024 H1 等更早季度須接 **SEC 10-Q 歷史**(companyconcept,流量科目要差分 YTD)→ 未做,留 TODO。
  - YoY 修正:季度模式 `_grade_second(yoy_lag=4)` 比「去年同季」,避開季節性(非 QoQ)。
  - `YearMetrics` 加 `period_label` 欄位(年度為 None,台股不受影響)。
- **族群 label**:`backend/us_sectors.py`(新)。人工維護 `PEER_GROUPS`(運算晶片/網通ASIC/記憶體/晶圓代工/光通CPO/被動元件/資料中心電源/EDA)。`/fin amd` → 認得族群 → 抓同族群近 5/20/60 交易日漲幅排行 + 族群均值熱度判讀,附在四刀輸出末尾。漲幅複用 `_fetch_us_daily`。
- **踩坑修**:`_fetch_us_daily` 原本 `if x.get("close")` 沒擋 NaN(Python `bool(nan)=True`),當日盤中未完成 bar 的 NaN close 漏進去 → 整串 MA/漲幅變 NaN。已改成 `close != close` 過濾。
- TODO:美股族群清單可再擴(探針卡/電池/載板等使用者關心題材);族群熱度可接真實 screener。

## ⚠️ 重啟踩坑(2026-06-16,已記 反覆踩坑.md)
watchdog `start_smc_bot.bat` 崩潰後 **5 秒**就重啟,< Telegram getUpdates 鎖釋放時間(~50s)。
若舊實例的連線還沒釋放就重啟,新實例撞 `telegram.error.Conflict` → 崩 → 5s 又起 → **無限 crash-loop**。
**正解**:重啟時先殺 watchdog cmd(父程序,擋它立即重生)+ 殺 python,**全死後**再用 `launch_smc_bot.vbs` 單一啟動,等 log 出現新的 `Application started`。只殺 python 會被 watchdog 5s 內重生而撞鎖。

## 現有指令(台股版已成形)
- `/fin <代號>` 單檔鑽豹四刀(第二刀基本面+大猩猩+第一刀+第三刀+綜合結論)
- `/blade1` 第一刀 watcher(觀察名單 `data/blade1_watchlist.json`,盤後15:00自動)
- `/hot` 熱門族群雷達(盤後14:00自動)

## 環境
- 系統 Python313(有 requests/pandas/shioaji);yfinance 待裝
- bot 啟動:雙擊 `啟動SMC機器人.bat`(純ASCII、watchdog自動重啟、開機自啟);重啟見 `反覆踩坑.md`
