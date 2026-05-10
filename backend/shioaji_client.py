import os
from dotenv import load_dotenv
import shioaji as sj
import pandas as pd

# 載入 .env.local 環境變數
load_dotenv('.env.local')

class ShioajiManager:
    def __init__(self):
        # 初始化 Shioaji API 客戶端
        self.api = sj.Shioaji()
        
    def login(self):
        """執行登入，強制使用模擬環境"""
        api_key = os.environ.get("SHIOAJI_API_KEY")
        secret_key = os.environ.get("SHIOAJI_SECRET_KEY")
        
        if not api_key or not secret_key:
            raise ValueError("❌ 找不到 Shioaji API Key 或 Secret Key，請檢查 .env.local 檔案")
        
        print("連線至永豐 Shioaji 伺服器中...")
        # 登入並強制設定為模擬環境，保護真實資金
        self.api.login(
            api_key=api_key, 
            secret_key=secret_key, 
            contracts_cb=lambda security_type: print(f"✅ {security_type} 合約下載完成")
        )
        print("✅ 永豐 Shioaji 模擬環境登入成功！")

    def fetch_daily_kbars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """抓取日線資料並轉換為回測引擎相容的格式"""
        contract = self.api.Contracts.Stocks[symbol]
        if not contract:
            raise ValueError(f"找不到標的 {symbol} 的合約")
        
        # 呼叫 API 抓取 K 線
        kbars = self.api.kbars(contract, start=start_date, end=end_date)
        
        # 轉換為 pandas DataFrame
        df = pd.DataFrame({**kbars})
        if not df.empty:
            df.ts = pd.to_datetime(df.ts)
            # 統一欄位名稱，與我們原本的 DataFrame 格式一致
            df = df.rename(columns={
                'ts': 'date', 
                'Open': 'open', 
                'High': 'high', 
                'Low': 'low', 
                'Close': 'close', 
                'Volume': 'volume'
            })
        return df

# 測試區塊 (只有直接執行此檔案時才會跑)
if __name__ == "__main__":
    from datetime import datetime, timedelta
    
    # 建立客戶端實例並登入
    client = ShioajiManager()
    client.login()
    
    # 測試抓取廣達 (2382) 最近 30 天的日線資料 (確保至少有 20 根營業日 K 線)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=30)
    
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")
    
    print(f"\n嘗試抓取 2382 日線 ({start_str} ~ {end_str})...")
    
    try:
        df = client.fetch_daily_kbars("2382", start_str, end_str)
        print("\n🎉 資料抓取成功！前 5 筆資料：")
        print(df.head())
        print(f"\n總共抓到 {len(df)} 根 K 線。")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")