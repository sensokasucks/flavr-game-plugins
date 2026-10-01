@echo off
cd /d "%~dp0"
python mock\mock_server.py
if errorlevel 1 pause
