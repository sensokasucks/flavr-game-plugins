@echo off
REM Schedule I mock mod (:3857), so Stream Core's Schedule I plugin can be tried without the game.
cd /d "%~dp0"
python mock\mock_server.py %*
if errorlevel 1 pause
