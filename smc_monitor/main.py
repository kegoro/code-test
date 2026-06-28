# ============================================================
#  main.py
#  SMC Signal Monitor · 主程式入口
# ============================================================

import sys
import os

# 確保 project root 在 Python path
sys.path.insert(0, os.path.dirname(__file__))

from notifier.telegram_bot import run_bot

if __name__ == "__main__":
    run_bot()
