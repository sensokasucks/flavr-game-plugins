@echo off
setlocal
cd /d "%~dp0"
title Fridge Minecraft NeoForge
echo Building Fridge Minecraft for NeoForge 21.1.248 + Create 6
where java >nul 2>&1
if errorlevel 1 (
  echo JDK 21 required
  pause
  exit /b 1
)
if not exist "gradle\wrapper\gradle-wrapper.jar" (
  echo Downloading gradle-wrapper.jar
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/gradle/gradle/raw/v8.14.3/gradle/wrapper/gradle-wrapper.jar' -OutFile 'gradle\wrapper\gradle-wrapper.jar'"
)
call gradlew.bat build --warning-mode none
if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 1
)
echo.
echo Jar: build\libs\fridge-minecraft-neoforge-1.0.0.jar
echo Drop into the NeoForge 1.21.1 mods folder WITH Create 6.x
echo Stream Core still talks to http://127.0.0.1:3853
pause
exit /b 0
