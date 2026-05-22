"""
Shioaji 連線測試腳本
執行方式：python test_shioaji.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 載入 .env.local
env_path = Path(__file__).parent / ".env.local"
if not env_path.exists():
    print("❌ 找不到 .env.local，請確認路徑")
    sys.exit(1)

load_dotenv(env_path)

api_key    = os.getenv("SHIOAJI_API_KEY")
secret_key = os.getenv("SHIOAJI_SECRET_KEY") or os.getenv("SHIOAJI_API_SECRET")

print("=" * 50)
print("🔍 Shioaji 連線測試")
print("=" * 50)

# Step 1: 確認 Key 存在
print(f"\n[1] API Key:    {'✅ 存在' if api_key    else '❌ 缺少'}")
print(f"    Secret Key: {'✅ 存在' if secret_key else '❌ 缺少'}")

if not api_key or not secret_key:
    print("\n❌ 請先在 .env.local 填入 Key")
    sys.exit(1)

# Step 2: 嘗試登入
print("\n[2] 嘗試登入永豐伺服器...")
try:
    import shioaji as sj
    api = sj.Shioaji()
    api.login(
        api_key=api_key,
        secret_key=secret_key,
        contracts_cb=lambda t: print(f"    📦 合約下載：{t}"),
    )
    print("✅ 登入成功！")
except Exception as e:
    print(f"❌ 登入失敗：{e}")
    print("\n可能原因：")
    print("  1. Key 已過期（永豐每年需重新申請）")
    print("  2. 網路問題")
    print("  3. 帳號被鎖定")
    sys.exit(1)

# Step 3: 抓取 2330 日線
print("\n[3] 測試抓取 2330（台積電）日線...")
try:
    from datetime import datetime, timedelta
    contract = api.Contracts.Stocks["2330"]
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    kbars = api.kbars(contract, start=start, end=end)

    import pandas as pd
    df = pd.DataFrame({**kbars})
    print(f"✅ 日線抓取成功，共 {len(df)} 根 K 線")
    print(df.tail(3).to_string())
except Exception as e:
    print(f"❌ 日線抓取失敗：{e}")

# Step 4: 抓取 2330 分鐘線
print("\n[4] 測試抓取 2330 分鐘線（今天）...")
try:
    today = datetime.now().strftime("%Y-%m-%d")
    kbars_m = api.kbars(contract, start=today, end=today)
    df_m = pd.DataFrame({**kbars_m})
    if df_m.empty:
        print("⚠️  分鐘線為空（可能今天休市或盤前）")
    else:
        print(f"✅ 分鐘線抓取成功，共 {len(df_m)} 根")
        print(df_m.tail(3).to_string())
except Exception as e:
    print(f"❌ 分鐘線抓取失敗：{e}")

print("\n" + "=" * 50)
print("測試完成")
print("=" * 50)
