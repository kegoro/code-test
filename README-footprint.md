# Footprint Chart 全端系統

台股／期貨即時 Footprint Chart 整合方案：FastAPI 後端聚合 Tick 資料，klinecharts 前端 Overlay 渲染。

---

## 系統架構

```
┌────────────────────────────────────────────────────────────────────┐
│  後端 (Python / FastAPI)                                           │
│                                                                    │
│   MockTickGenerator                                                │
│   (未來 → ShioajiTickFeed)                                         │
│         │                                                          │
│         │ RawTick dict                                             │
│         ▼                                                          │
│   asyncio.Queue(maxsize=1000)                                      │
│         │                                                          │
│         ▼                                                          │
│   StreamingFootprintAggregator                                     │
│   (切棒 / POC / Imbalance)                                         │
│         │                                                          │
│         ├── GET  /api/footprint/history?bars=N   ──┐               │
│         └── WS   /ws/footprint                     │               │
│              {snapshot|bar_update|bar_close}       │               │
└────────────────────────────────────────────────────┼───────────────┘
                                                     │
                                                     ▼
┌────────────────────────────────────────────────────────────────────┐
│  前端 (Next.js / React 19)                                         │
│                                                                    │
│   useFootprintSocket(url, barSeconds)                              │
│         │  bars / currentBar / isConnected / error                 │
│         ▼                                                          │
│   <FootprintChart />                                               │
│         │                                                          │
│         ├── klinecharts.init                                       │
│         └── registerFootprintOverlay  → 量能格 / POC / Δ          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 啟動步驟

### 1. 後端

```bash
# 從 repo 根目錄
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

驗證：
```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/footprint/history?bars=5'
```

### 2. 前端

```bash
npm install        # 第一次安裝（zod / klinecharts 已在 package.json）
npm run dev        # next dev
```

在頁面中使用：
```tsx
import { FootprintChart } from '@/components/charts/FootprintChart';

export default function Page() {
  return <FootprintChart symbol="TXFF4" />;
}
```

### 3. 整合測試

```bash
bash scripts/test-integration.sh
```
依賴：`curl`、`jq`、`websocat`、`python`。

---

## Mock → Shioaji 切換

只需替換一個檔案中的一行：

> `backend/main.py` 的 `lifespan()` 中，把 `MockTickGenerator(state.tick_queue)` 換成 `ShioajiTickFeed(state.tick_queue, contracts=[...])`，並讓新類別共用同一個 `asyncio.Queue` 介面（`put_nowait(tick_dict)`）即可，其餘聚合、WS、前端零改動。

`RawTick` 欄位命名（`code/datetime/price/volume/total_volume/tick_type/bid_side_total_vol/ask_side_total_vol`）已 100% 對齊 Shioaji `quote_callback` 規格。

---

## 檔案職責

| 路徑 | 職責 |
|------|------|
| `src/types/footprint.ts` | 共用型別（RawTick、FootprintBar、FootprintLevel、WS 訊息） |
| `backend/mock_tick_generator.py` | 模擬 Tick 來源；未來抽換為 Shioaji |
| `backend/footprint_aggregator.py` | 純函數 + Streaming 聚合器（POC / Imbalance / 切棒） |
| `backend/main.py` | FastAPI app：HTTP `/api/footprint/history`、WS `/ws/footprint` |
| `src/lib/footprint-aggregator.ts` | 前端可選用的 client-side 聚合器（保留以備離線模式） |
| `src/lib/footprint-aggregator.test.ts` | Vitest 單元測試（18 例） |
| `src/hooks/useFootprintSocket.ts` | WS 連線、自動重連、historyAPI 載入、zod 驗證 |
| `src/components/charts/FootprintOverlay.ts` | klinecharts overlay：每棒繪製 Bid/Ask 量能格、POC、Δ |
| `src/components/charts/FootprintChart.tsx` | 對外完整元件：含連線指示燈、Δ 浮層、Loading |
| `scripts/test-integration.sh` | 端對端整合測試 |

---

## 訊息協定

WS `/ws/footprint` 推送：

```json
{ "type": "snapshot",   "data": [FootprintBar, ...] }
{ "type": "bar_update", "data": FootprintBar }
{ "type": "bar_close",  "data": FootprintBar }
```

HTTP `/api/footprint/history?bars=N`：

```json
{
  "barSeconds": 60,
  "bars": [FootprintBar, ...],
  "current": FootprintBar | null
}
```
