@echo off
setlocal

set "LAUNCHER_DIR=%~dp0"
for %%I in ("%LAUNCHER_DIR%..") do set "PROJECT_DIR=%%~fI"
set "SCRIPT=%PROJECT_DIR%\run_batch_meshing_panel.py"

cd /d "%PROJECT_DIR%"

if not exist "%SCRIPT%" (
    echo Cannot find run_batch_meshing_panel.py:
    echo %SCRIPT%
    echo.
    pause
    exit /b 1
)

where pyw.exe >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    start "" /D "%PROJECT_DIR%" pyw.exe -3 "%SCRIPT%"
    exit /b 0
)

where pythonw.exe >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    start "" /D "%PROJECT_DIR%" pythonw.exe "%SCRIPT%"
    exit /b 0
)

where py.exe >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    start "" /D "%PROJECT_DIR%" py.exe -3 "%SCRIPT%"
    exit /b 0
)

where python.exe >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    start "" /D "%PROJECT_DIR%" python.exe "%SCRIPT%"
    exit /b 0
)

echo Cannot find Python launcher.
echo Please install Python or add py.exe/python.exe to PATH.
echo.
pause
