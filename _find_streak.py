import pandas as pd

df = pd.read_csv("data/bt_noc1.csv")
trades = df[df["trade_taken"] == True].copy().reset_index(drop=True)

max_streak = cur_streak = cur_start = best_start = best_end = 0

for i, row in trades.iterrows():
    if row["pnl_pts"] <= 0:
        if cur_streak == 0:
            cur_start = i
        cur_streak += 1
        if cur_streak > max_streak:
            max_streak = cur_streak
            best_start = cur_start
            best_end = i
    else:
        cur_streak = 0

streak = trades.loc[best_start:best_end][
    ["date", "direction", "exit_reason", "pnl_pts", "or_range", "bias_a"]
]
print(f"最長連敗：{max_streak} 筆，{trades.loc[best_start,'date']} ～ {trades.loc[best_end,'date']}\n")
print(streak.to_string(index=False))
