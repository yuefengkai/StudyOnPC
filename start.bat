@echo off
rem Hidden start — no lingering Python console. Debug: start-console.bat
cd /d "%~dp0"
wscript //nologo "%~dp0scripts\run_hidden.vbs"
