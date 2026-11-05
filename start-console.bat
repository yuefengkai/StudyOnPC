@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
if exist logs\stop.flag del /f /q logs\stop.flag
echo StudyOnPC 控制台调试模式（会显示黑窗口）。正常请用 start.bat / start.vbs。
if exist "%~dp0StudyOnPC.exe" (
  "%~dp0StudyOnPC.exe" --console --role=main --force %*
) else (
  python studyonpc.py --console --role=main --force %*
)
