"""
Installs start_daemon.bat into Windows Startup folder so the daemon
auto-starts every time you log into Windows.

Run once:  python install_startup.py
Remove:    python install_startup.py --uninstall
"""
import sys
import shutil
from pathlib import Path

STARTUP = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
BAT_SRC  = Path(__file__).parent / "start_daemon.bat"
BAT_DST  = STARTUP / "tw-stock-signal.bat"

def install():
    shutil.copy2(BAT_SRC, BAT_DST)
    print(f"✅ 已安裝到 Windows 開機自動啟動：\n   {BAT_DST}")
    print("   下次登入 Windows 時 daemon 會自動在背景視窗啟動。")

def uninstall():
    if BAT_DST.exists():
        BAT_DST.unlink()
        print(f"✅ 已從開機自動啟動移除：{BAT_DST}")
    else:
        print("⚠️  尚未安裝，無需移除。")

if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
