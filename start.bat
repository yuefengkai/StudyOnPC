@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
if exist logs\stop.flag del /f /q logs\stop.flag
echo 正在隐藏启动 StudyOnPC（关掉这个黑窗口也停不掉）...
if exist "%~dp0StudyOnPC.exe" (
  start "" /min "%~dp0StudyOnPC.exe" --role=watchdog
) else (
  wscript "%~dp0scripts\run_hidden.vbs"
)
echo 已启动。家长退出：Ctrl+Shift+Q；管理页 http://127.0.0.1:8099/
timeout /t 2 >nul
