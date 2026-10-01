@echo off
REM Fridge Workshop - Granvir mock stats server (:3855)
setlocal
cd /d "%~dp0"
set "APP=%~dp0fridge-granvir-stats"
if not exist "%APP%\START Mock.bat" (
  echo [ERROR] fridge-granvir-stats\START Mock.bat not found.
  pause
  exit /b 1
)
call "%APP%\START Mock.bat"
endlocal
