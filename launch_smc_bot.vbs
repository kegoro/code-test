' Launch SMC bot hidden, no console window.
' Put a shortcut to this file in the Windows Startup folder for auto-start on boot.
' IMPORTANT: keep this file ASCII-only. Chinese text here breaks wscript (Big5 vs UTF-8).
CreateObject("WScript.Shell").Run """C:\Users\sfudally\Desktop\code test\start_smc_bot.bat""", 0, False
