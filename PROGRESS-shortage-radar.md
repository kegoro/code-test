# PROGRESS — 缺貨雷達（shortage_radar）

**最後更新**：2026-06-14

> 跨對話進度記憶。新對話說「繼續缺貨雷達」→ 先讀本檔再接手。
> 規則/判斷依據在 [`雷老闆心法.md`](雷老闆心法.md)；本檔只記**進度/狀態/計畫**。

---

## 目標
找出「供需曲線**左上（價高量少）= 缺貨**」的產業/個股。
理論：雷老闆心法.md 指標一供需曲線 + 面談原則A「缺字哲學」。
缺貨財報指紋：① 合約負債↑ ② 毛利率↑ ③ 營收YoY↑ ④ 景氣升時存貨↑。

## 關鍵決策（已與擁有者確認，不可擅改）
| 決策 | 內容 | 理由 |
|------|------|------|
| 介面 | **Telegram 推播，不建戰情室前端** | 產出是「缺貨清單/排行」非互動儀表板；使用者不寫程式、靠 TG 驅動；紙上模擬期先驗證邏輯（YAGNI） |
| 資料深度 | **兩層**：第一層財報代理（FinMind免費）+ 第二層產業報價 | 使用者要接近真實價量；但財報無法拆 P/Q，需報價補 |
| 掃描範圍 | **全市場各產業自動掃** | 使用者要全覆蓋、找出所有缺貨產業 |
| 送訊 | 走 SMC bot（同 daily_signal._send_telegram） | 與盤前報告一致（LESSONS §1.5） |

## Phase 狀態
| Phase | 內容 | 狀態 |
|-------|------|------|
| **1** | 財報代理引擎：單檔缺貨分數(0~6) + 主題/單產業掃描 + 排行 | ✅ **完成**（`backend/shortage_radar.py`，CCL 主題驗證通過） |
| **1.5** | 全市場分批掃 + API限流 + 季快取 + 產業聚合排行 + 接 TG 排程 | ⛔ 未開始（**下一步**） |
| **2** | 產業報價層（真正價量拆解） | ⛔ 未開始（逐源爬，見下） |

## Phase 1 已完成內容（`backend/shortage_radar.py`）
- `shortage_score(code,name)` → 0~6 分：合約負債趨勢2 + 毛利QoQ/YoY 2 + 營收YoY 1 + 存貨備貨1
- `scan(tickers)`：批次跑 + 排行（內含 `_SLEEP=0.3` 限流）
- `aggregate_by_industry()`：產業聚合（avg / hot數），**已寫好但 1.5 才會用到**
- CLI：`--theme ccl|optical|probe`、`--industry <名>`(限30檔)、`--codes ...`、`--tg`
- 跑法：`C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe -m backend.shortage_radar --theme ccl`
- **實測(2026-06-14)**：CCL → 南電8046[5/6]、台燿6274[4/6]、台光電2383[3/6]、聯茂6213[1/6]，缺貨指紋明顯。

## Phase 1.5 下一步（接手就做這個）
1. **全市場掃描器**：用 `season.py` 的 `stock_industry.json`（3101檔）反查各產業成分股。
2. **API 限流/快取**（關鍵）：FinMind 免費版有上限，全市場×3 dataset 會爆 →
   - 季財報變動慢 → 結果快取 `data/shortage_cache_<季>.json`，同季不重抓
   - 分批（每批 N 檔 + sleep）、可跨多次執行續跑
   - 或每產業只抽代表股（市值/成交額前 N；市值需另抓，FinMind 無 → 可用近月成交額近似）
3. **產業聚合排行** → 每週推 TG「缺貨產業 TOP + 代表股」。
4. **排程**：接 smc_bot（季報公布後跑，如每週一次；非每日，季資料不變）。

## Phase 2 待做：產業報價層（逐源，部分可能付費）
| 主題 | 報價來源（待查證） | 備註 |
|------|-------------------|------|
| 貨櫃航運 | SCFI 上海出口集裝箱運價指數 | 公開週更 |
| 散裝航運 | BDI 波羅的海乾散貨指數 | 公開 |
| 記憶體 | DRAMeXchange / TrendForce 現貨價 | 部分付費 |
| CCL/載板 | 銅價(LME)、玻纖布報價、法人報告 | 銅價公開，CCL報價較難 |
| 光通訊/高頻 | 法人報告、廠商BOM | 難，多靠新聞 |
- 第二層目的：把財報代理的「疑似缺貨」用報價確認「價漲量縮」真供需。
- 可先接「公開且免費」的 SCFI/BDI/銅價，難取得的(DRAM/CCL報價)後議。

## 環境
- **務必用系統 Python**：`C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe`（venv 無 requests/pandas，見 LESSONS §1.4）
- FinMind token：`.env.local` 的 `FINMIND_API_TOKEN`
- 缺料主題清單在 `shortage_radar.THEMES`（ccl/optical/probe，可續加；代號名稱以 ticker_name 跑出為準）

## 待人工確認
- `THEMES` 的 optical/probe 成分股代號是我初擬，**需擁有者確認是否正確/補齊**（CCL 已驗證合理）。
