@echo off
REM Double-click to open the Smelt inbox in your browser.
cd /d "%~dp0"
".venv\Scripts\smelt.exe" serve
pause
