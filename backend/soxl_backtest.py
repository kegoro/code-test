"""SOXL 日線順勢策略回測 — 誠實版(無前視 / 含成本 / 跨年度交叉樣本)。

定位:這是「日線 swing」回測(資料夠、可信),回答「長期+逐年,SOXL 順勢做多
有沒有邊際」。**不是日內當沖回測** —— 日內受分鐘K資料深度限制(LESSONS §2.8.4),
免費資料源跑不到 90-180 天,故當沖請用 Pine 視覺驗證 + 將來付費資料源。

執行假設(無前視,對齊 LESSONS §2.8.2 教訓):
  訊號用「當日收盤」算 → 部位 shift 1 天才套用(等於隔日進場),
  換倉每邊扣 0.05% 成本/滑價,close-to-close 報酬,long-only。

用法: python -m backend.soxl_backtest [SOXL] [TQQQ ...]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import yfinance as yf

SLIP = 0.0005  # 每邊成本/滑價(換倉時)


def fetch(symbol: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    if df is None or df.empty:
        raise SystemExit(f"{symbol}: 取不到資料")
    df = df[["Open", "High", "Low", "Close"]].dropna().copy()
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_localize(None) if idx.tz is not None else idx
    return df


def equity_stats(strat_ret: pd.Series) -> dict:
    eq = (1.0 + strat_ret).cumprod()
    years = len(strat_ret) / 252.0
    total = float(eq.iloc[-1] - 1.0)
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    maxdd = float((eq / eq.cummax() - 1.0).min())
    return {"total": total, "cagr": cagr, "maxdd": maxdd}


def trade_stats(pos: pd.Series, ret: pd.Series) -> dict:
    """連續 pos==1 視為一筆交易,算勝率/獲利因子/期望值。"""
    daily = (pos * ret).to_numpy()
    p = pos.to_numpy()
    trades: list[float] = []
    in_t, cur = False, 0.0
    for i in range(len(p)):
        if p[i] == 1 and not in_t:
            in_t, cur = True, 0.0
        if in_t:
            cur = (1.0 + cur) * (1.0 + daily[i]) - 1.0
        if p[i] == 0 and in_t:
            trades.append(cur)
            in_t = False
    if in_t:
        trades.append(cur)
    t = np.array(trades)
    if len(t) == 0:
        return {"n": 0}
    wins, losses = t[t > 0], t[t <= 0]
    pf = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
    return {
        "n": int(len(t)), "wr": float(len(wins) / len(t)), "pf": pf,
        "exp": float(t.mean()),
        "avgw": float(wins.mean()) if len(wins) else 0.0,
        "avgl": float(losses.mean()) if len(losses) else 0.0,
    }


def make_signals(df: pd.DataFrame) -> dict:
    close = df["Close"]
    sma200 = close.rolling(200).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    return {
        "Regime(SMA200)": close > sma200,                       # 站上 200 日線才抱
        "Regime+EMA20": (close > sma200) & (close > ema20),     # 加 20 日過濾,少抱回檔
    }


def backtest(df: pd.DataFrame, sig: pd.Series):
    ret = df["Close"].pct_change(fill_method=None).fillna(0.0)
    pos = sig.shift(1).fillna(False).astype(int)                # 無前視:昨收訊號→今日部位
    cost = SLIP * pos.diff().abs().fillna(0.0)
    net = pos * ret - cost
    return ret, pos, net


def main() -> None:
    syms = sys.argv[1:] or ["SOXL"]
    for sym in syms:
        df = fetch(sym)
        bh = df["Close"].pct_change(fill_method=None).fillna(0.0)
        bhs = equity_stats(bh)
        print("=" * 64)
        print(f"{sym} 日線回測  {df.index[0].date()} → {df.index[-1].date()}  共 {len(df)} 根")
        print(f"[Buy & Hold] 總報酬 {bhs['total']*100:,.0f}%  CAGR {bhs['cagr']*100:,.1f}%  最大回撤 {bhs['maxdd']*100:,.1f}%")

        sigs = make_signals(df)
        nets: dict[str, pd.Series] = {}
        for name, sig in sigs.items():
            ret, pos, net = backtest(df, sig)
            nets[name] = net
            es, ts = equity_stats(net), trade_stats(pos, ret)
            print(f"\n[{name}]  在場時間 {pos.mean()*100:.0f}%")
            print(f"  總報酬 {es['total']*100:,.0f}%  CAGR {es['cagr']*100:,.1f}%  最大回撤 {es['maxdd']*100:,.1f}%")
            if ts.get("n"):
                print(f"  交易 {ts['n']} 筆  勝率 {ts['wr']*100:.0f}%  獲利因子 {ts['pf']:.2f}  "
                      f"每筆期望 {ts['exp']*100:+.2f}%  (均贏 {ts['avgw']*100:+.1f}% / 均輸 {ts['avgl']*100:+.1f}%)")

        # 逐年交叉樣本:避免被單一多頭年份(如 2023-24 AI 行情)騙
        print("\n逐年報酬%(交叉樣本 — 看是否每年一致,而非單年暴賺):")
        print(f"  {'年':<6}{'B&H':>8}" + "".join(f"{n[:12]:>14}" for n in sigs))
        for y in sorted({d.year for d in df.index}):
            m = df.index.year == y
            row = f"  {y:<6}{(((1+bh[m]).prod()-1)*100):>8.0f}"
            for n in sigs:
                row += f"{(((1+nets[n][m]).prod()-1)*100):>14.0f}"
            print(row)
        print("\n註:日線 swing 結果。日內當沖另需分鐘K(資料受限)。長期/逐年不一致 = 沒真邊際。")


if __name__ == "__main__":
    main()
