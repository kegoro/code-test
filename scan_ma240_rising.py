import io
import time
import requests
import urllib3
import pandas as pd
import yfinance as yf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from concurrent.futures import ThreadPoolExecutor, as_completed

RECENT_DAYS = 5
MA_WINDOW = 240
OUTPUT_CSV = "ma240_rising.csv"


def get_listed_tickers():
    url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    r = requests.get(url, timeout=30, verify=False)
    r.encoding = "big5"
    tables = pd.read_html(io.StringIO(r.text))
    df = tables[0]
    df.columns = df.iloc[0]
    df = df.iloc[1:]
    df = df[df["CFICode"].astype(str).str.startswith("ESVUFR")]
    codes = df["有價證券代號及名稱"].astype(str).str.split(expand=True)
    out = pd.DataFrame({"code": codes[0], "name": codes[1]})
    out = out[out["code"].str.match(r"^\d{4}$")]
    return out.reset_index(drop=True)


def check_rising(ticker):
    try:
        df = yf.download(
            ticker, period="2y", interval="1d",
            auto_adjust=False, progress=False, threads=False,
        )
        if df.empty or len(df) < MA_WINDOW + RECENT_DAYS:
            return None
        close = df["Close"].squeeze()
        ma = close.rolling(MA_WINDOW).mean().dropna()
        if len(ma) < RECENT_DAYS + 1:
            return None
        tail = ma.iloc[-(RECENT_DAYS + 1):]
        diffs = tail.diff().dropna()
        if (diffs > 0).all():
            return {
                "ticker": ticker,
                "last_close": float(close.iloc[-1]),
                "ma240": float(ma.iloc[-1]),
                "ma240_change_pct": float((ma.iloc[-1] / ma.iloc[-RECENT_DAYS - 1] - 1) * 100),
            }
    except Exception:
        return None
    return None


def main():
    listed = get_listed_tickers()
    print(f"上市股票數: {len(listed)}")
    tickers = [f"{c}.TW" for c in listed["code"]]
    name_map = dict(zip([f"{c}.TW" for c in listed["code"]], listed["name"]))

    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_rising, t): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r:
                r["name"] = name_map.get(r["ticker"], "")
                results.append(r)
            if i % 50 == 0:
                print(f"進度: {i}/{len(tickers)}  命中: {len(results)}")

    out = pd.DataFrame(results)
    if not out.empty:
        out = out[["ticker", "name", "last_close", "ma240", "ma240_change_pct"]]
        out = out.sort_values("ma240_change_pct", ascending=False)
        out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n完成 共 {len(out)} 檔 → {OUTPUT_CSV}")
    if not out.empty:
        print(out.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
