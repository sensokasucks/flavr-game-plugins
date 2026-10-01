@echo off
REM Fridge Factorio Stats – Node bridge + overlay (:3847)
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "server\server.js" (
  echo [ERROR] server\server.js not found.
  pause
  exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not on PATH. Install from https://nodejs.org/
  pause
  exit /b 1
)

if not exist "server\node_modules" (
  echo First run: npm install in server\ ...
  pushd server
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed.
    popd
    pause
    exit /b 1
  )
  popd
)

echo Starting Factorio stats bridge on http://127.0.0.1:3847/
echo Overlay: http://127.0.0.1:3847/overlay.html
echo Press Ctrl+C to stop.
echo.
pushd server
node server.js
set EXITCODE=%ERRORLEVEL%
popd
if not %EXITCODE%==0 pause
endlocal
exit /b %EXITCODE%
