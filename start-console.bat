@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
if exist logs\stop.flag del /f /q logs\stop.flag
echo StudyOnPC 控制台模式。Ctrl+Shift+Q 退出。
if exist "%~dp0StudyOnPC.exe" (
  "%~dp0StudyOnPC.exe" --role=main --force %*
) else (
  python studyonpc.py --role=main --force %*
)
