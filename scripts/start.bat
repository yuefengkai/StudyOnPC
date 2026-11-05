@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist logs mkdir logs
if exist logs\stop.flag del /f /q logs\stop.flag
echo 正在隐藏启动 StudyOnPC（关掉这个黑窗口也停不掉）...
wscript "%~dp0run_hidden.vbs"
echo 已启动。家长退出：Ctrl+Shift+Q 输入 PIN；或运行 scripts\parent_quit.ps1
echo 管理页：http://127.0.0.1:8099/
timeout /t 2 >nul
