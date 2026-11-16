@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%配置HM+ANSA同时划分环境.ps1" -ProjectDir "%SCRIPT_DIR%.."
echo.
pause
