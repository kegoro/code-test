# -*- coding: utf-8 -*-
"""抓光聖(6442)MOPS 合併損益表+現金流量表,近5年。單位:仟元。"""
import requests, re, time, json
from bs4 import BeautifulSoup

HEAD = {"User-Agent": "Mozilla/5.0"}
CO = "6442"

def fetch(report, year):
    url = f"https://mopsov.twse.com.tw/mops/web/ajax_{report}"
    data = {"encodeURIComponent":"1","step":"1","firstin":"1","off":"1",
            "queryName":"co_id","inpuType":"co_id","TYPEK":"all","isnew":"false",
            "co_id":CO,"year":str(year),"season":"04"}
    r = requests.post(url, data=data, headers=HEAD, timeout=40)
    r.encoding = "utf-8"
    return r.text

def num(s):
    s = s.strip().replace(",", "").replace("\xa0", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not re.match(r'^-?\d+(\.\d+)?$', s):
        return None
    v = float(s)
    return -v if neg else v

def find_row(html, pred):
    """回傳第一個 name 符合 pred 的列的『本期金額』(name 後第一個可解析數字)。"""
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not tds:
            continue
        name = tds[0].replace(" ", "").replace("　", "")
        if pred(name):
            for cell in tds[1:]:
                v = num(cell)
                if v is not None:
                    return v
    return None

out = {}
for y in range(110, 115):  # 民110~114 = 2020報表的後一年...實際2021~2025
    west = y + 1911
    is_html = fetch("t164sb04", y)
    rev   = find_row(is_html, lambda n: n == "營業收入合計")
    gross = find_row(is_html, lambda n: n.startswith("營業毛利") and "淨額" in n) \
            or find_row(is_html, lambda n: n.startswith("營業毛利"))
    opinc = find_row(is_html, lambda n: n.startswith("營業利益"))
    time.sleep(1.0)
    cf_html = fetch("t164sb05", y)
    ocf   = find_row(cf_html, lambda n: "營業活動之淨現金" in n)
    capex = find_row(cf_html, lambda n: "取得不動產" in n and "設備" in n)
    fcf = (ocf + capex) if (ocf is not None and capex is not None) else None
    out[west] = {"營收": rev, "毛利": gross, "營業利益": opinc,
                 "OCF": ocf, "取得不動產廠房設備": capex, "FCF": fcf}
    print(west, json.dumps(out[west], ensure_ascii=False))
    time.sleep(1.0)

print("=====JSON=====")
print(json.dumps(out, ensure_ascii=False, indent=2))
