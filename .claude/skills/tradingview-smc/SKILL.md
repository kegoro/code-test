---
name: tradingview-smc
description: ICT/SMC 當沖方法論（BOS、Volume Profile/POC/VAL/VAH、FVG、流動性獵取 sweep、SNR 支阻轉換、London high/low、進場模型、止損止盈）與對應的 TradingView Pine 指標。當使用者問這些名詞、要在 TradingView 畫這些結構、或要產生／修改對應 Pine Script 時使用。
---

# TradingView ICT/SMC 當沖方法論

> 這份是給 Claude 讀的知識手冊。使用者（不寫程式）靠它讓我「一叫就懂這套」，並能直接幫他生／改對應的 Pine Script、或判讀盤面。
> 對應的客製 Pine 指標：`tradingview/smc_daytrade.pine`（可貼進 TradingView Pine 編輯器自動畫圖）。

## ⚠️ 市場適用性（最重要，先看）

這整套（BOS / FVG / 流動性獵取 / London high-low）是 **ICT/SMC 流派，為 24 小時市場設計**。

| 使用者市場 | 適用？ | 原因 |
|---|---|---|
| **加密貨幣** BTC/ETH/SOL/BNB（24h） | ✅ 完全適用 | 這套本來就是給 24h 市場用的 |
| **台股當沖** 09:00–13:30 | ❌ 當日無效 | 倫敦盤台北 ~15:00 才開，台股已收盤。London high/low 對台股只能當「隔日跳空背景」，不是當沖盤中獵殺劇本 |

**規則：使用者問「台股當沖」怎麼用 London → 直接糾正，別硬套。台股當沖請用已驗證的 N-Pattern（`backend/smc_analyst/setups/n_pattern.py`）+ `/cdp` 四線。**

## 名詞速查

| 名詞 | 定義 | TradingView 怎麼看 | 在模型裡的角色 |
|---|---|---|---|
| **BOS**（Break of Structure） | 價格突破前一個 swing 高/低 | 手畫 or Market Structure 類指標 | 定方向（趨勢續行；反向破壞＝MSS 反轉訊號） |
| **Volume Profile** | 各價位成交量分布 | 內建 Session/Fixed Range VP（部分需付費） | 看價值區與磁吸 |
| **POC**（Point of Control） | 成交量最大的價位 | VP 上最寬的那條 | 均值磁鐵、停利目標 |
| **VAL / VAH**（Value Area Low/High） | 涵蓋約 70% 成交量區間的上下緣 | VP 著色區邊界 | 邊界，常反轉；停利/confluence |
| **FVG**（Fair Value Gap） | 急拉留下的 3 根 K 跳空失衡區 | FVG 類指標 or 手畫 | 回踩進場區（價傾向回補） |
| **流動性獵取**（liquidity grab / sweep） | 假突破掃掉前高/前低停損後反轉 | 標前高前低、等高等低 | **進場觸發**（先誘多/誘空再反向） |
| **SNR**（Support↔Resistance flip／支阻轉換） | 破掉的阻力變支撐（反之亦然） | 水平線 | 進場確認（回測不破才進） |
| **London high/low** | 倫敦時段最高/最低 | ICT Killzones / Sessions 指標 | **流動性池**（被獵取的目標價位） |

## 進場模型（勝率來源＝confluence，不是單一指標）

ICT 經典序列「流動性 → 掃 → 結構轉變 → FVG 進場」：

1. **HTF 定偏向**（4H/1H）：BOS 方向 + 現價在便宜區(discount，找多)或昂貴區(premium，找空)
2. **標流動性池**：London high/low、前日高低(PDH/PDL)、等高/等低
3. **等獵取**：價格**假突破**掃過流動性池後**收回** ← 別追那根突破
4. **LTF 確認**：5m/15m 出現反向 **BOS/MSS**
5. **進場**：回踩 **FVG**（或 OB、SNR 轉換線）才進；若該區又貼 **POC/VAL** → confluence 最強
6. **止損止盈**：SL 放**獵取那根的極端點外**；TP 放**對向流動性池**（另一側 London/PDH-PDL）或 **POC / 對向 VA 邊界**，吃滿 **R:R ≥ 2**

## London high/low 具體用法（crypto）

- TradingView 開「ICT Killzones」自動框 London box（台北約 15:00–23:00）與 high/low 線。
- 那兩條線是機構要吃的停損池：常見「London 做出當日高低 → 之後時段 sweep 它再反轉」。
- 最高勝率打法：**掃 London low + 收回 + LTF BOS↑ + 回踩 FVG 做多**（做空鏡像）。沒掃到流動性的突破不做。

## 對應 Pine 指標：`tradingview/smc_daytrade.pine`

- **會自動畫**：BOS（多/空標記）、FVG 框、London 高/低線、London 被掃三角標記+alert、前日高低 PDH/PDL。
- **不畫 POC/VP**：真實成交量分布請加 TradingView 內建 Session/Fixed Range Volume Profile 疊著看（Pine 近似不準，不做）。
- 使用者要新增/調整規則（如改 session 時間、加等高等低偵測）→ 直接改這支 Pine。

## 誠實話（每次都要扣回來）

- **勝率不是加指標加出來的。** 本專案 `LESSONS.md §2.8.4` 已實證：OB/FVG/Breaker/Mitigation/Trendline 多數 setup 30 天好看、90 天垮；只有 **N-Pattern 跨樣本穩**（BTC 90d 67%）。FVG@HTF 回測直接 0%。
- 拉勝率靠：① confluence（多條件齊才進）② 只在獵取後進、不追突破 ③ R:R ≥ 2 + 紀律 ④ **至少 90 天回測**才上線。
- 使用者最大漏洞是**紀律**（`§2.7.4c`：沒寫停損、超 3 筆、凹單），不是指標。任何 ICT 模型都救不了破紀律。

## 落地

- **Crypto**：把模型寫成 setup 丟進現有 backtest（對齊 live 窗口，見 `§2.8.2`），跑 90/180 天驗證再上線。可照 `n_pattern.py` 的 pure-function 樣式寫 `liquidity_sweep.py` + 測試。
- **台股當沖**：放掉 London，用 N-Pattern + `/cdp`（開盤定調：AH 追多、AL 放空、NH~NL 間觀望）。
