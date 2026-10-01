@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

title Fridge Minecraft - Build
echo.
echo  ========================================
echo   Fridge Minecraft - build both jars
echo  ========================================
echo.

where java >nul 2>&1
if errorlevel 1 (
  echo [ERROR] java not found on PATH.
  echo Install JDK 21 and reopen this window.
  echo https://adoptium.net/temurin/releases/?version=21
  goto :fail
)

echo Checking Java...
java -version
echo.

call :ensure_wrapper "client-mod"
call :ensure_wrapper "server-mod"

set "FAIL=0"

echo -------- client-mod --------
pushd client-mod
call gradlew.bat build --warning-mode none
if errorlevel 1 (
  echo [ERROR] client-mod build failed
  set "FAIL=1"
)
popd
echo.

echo -------- server-mod --------
pushd server-mod
call gradlew.bat build --warning-mode none
if errorlevel 1 (
  echo [ERROR] server-mod build failed
  set "FAIL=1"
)
popd
echo.

if "!FAIL!"=="1" goto :fail

echo -------- copy jars --------
if not exist "jars" mkdir jars

set "CLIENT_JAR="
for %%F in (client-mod\build\libs\fridge-minecraft-client-*.jar) do (
  echo %%~nxF | findstr /i "sources dev" >nul
  if errorlevel 1 set "CLIENT_JAR=%%F"
)
set "SERVER_JAR="
for %%F in (server-mod\build\libs\fridge-minecraft-server-*.jar) do (
  echo %%~nxF | findstr /i "sources dev" >nul
  if errorlevel 1 set "SERVER_JAR=%%F"
)

if not defined CLIENT_JAR (
  echo [ERROR] No client jar under client-mod\build\libs\
  set "FAIL=1"
)
if not defined SERVER_JAR (
  echo [ERROR] No server jar under server-mod\build\libs\
  set "FAIL=1"
)
if "!FAIL!"=="1" goto :fail

copy /Y "!CLIENT_JAR!" "jars\" >nul
copy /Y "!SERVER_JAR!" "jars\" >nul
echo Copied into jars\:
for %%F in ("!CLIENT_JAR!") do echo   %%~nxF
for %%F in ("!SERVER_JAR!") do echo   %%~nxF

set "MODS=%APPDATA%\.minecraft\mods"
if exist "%MODS%" (
  echo.
  choice /C YN /M "Also copy both jars into %MODS%"
  if errorlevel 2 goto :done
  copy /Y "!CLIENT_JAR!" "%MODS%\" >nul
  copy /Y "!SERVER_JAR!" "%MODS%\" >nul
  echo Installed into %MODS%
) else (
  echo.
  echo No %MODS% folder found — skip auto-install.
  echo Manually copy jars\*.jar into your Fabric mods folder.
)

:done
echo.
echo BUILD OK
echo Client stats port 3852 ^| Server commands/dynamo port 3853
echo Remember: Stream Core needs minecraft.enabled: true
echo.
pause
exit /b 0

:ensure_wrapper
set "WRAP=%~1\gradle\wrapper\gradle-wrapper.jar"
if exist "%WRAP%" (
  echo Wrapper OK: %WRAP%
  goto :eof
)
echo Missing %WRAP%
echo Downloading Gradle wrapper jar...
if not exist "%~1\gradle\wrapper" mkdir "%~1\gradle\wrapper"
powershell -NoProfile -Command ^
  "try { Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/gradle/gradle/raw/v8.14.3/gradle/wrapper/gradle-wrapper.jar' -OutFile '%WRAP%' } catch { exit 1 }"
if exist "%WRAP%" (
  echo Downloaded %WRAP%
  goto :eof
)
echo [ERROR] Could not download gradle-wrapper.jar
echo Get it from https://github.com/gradle/gradle/raw/v8.14.3/gradle/wrapper/gradle-wrapper.jar
echo and save as %WRAP%
set "FAIL=1"
goto :eof

:fail
echo.
echo BUILD FAILED — fix the errors above, then run BUILD.bat again.
echo Need JDK 21 and internet on the first run ^(Gradle + Loom downloads^).
echo If you saw "Unable to access jarfile ... gradle-wrapper.jar", the wrapper
echo was missing from git. Re-run BUILD.bat on a network so it can download.
echo.
pause
exit /b 1
