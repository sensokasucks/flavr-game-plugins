@echo off
REM Fridge Workshop - Schedule I mock mod (:3857)
setlocal
cd /d "%~dp0"
set "APP=%~dp0fridge-schedule1"
if not exist "%APP%\START Mock.bat" (
  echo [ERROR] fridge-schedule1\START Mock.bat not found.
  pause
  exit /b 1
)
call "%APP%\START Mock.bat"
endlocal
