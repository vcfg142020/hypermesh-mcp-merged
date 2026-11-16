@echo off
REM ---------------------------------------------------------------
REM  HyperMesh MCP - stdio 启动（旧入口，一般用不到）
REM  原脚本写死了 C:\Program Files\Altair\2020\...，换机必失效。
REM  改为调用 hwmcp/autodetect.py 自动发现，仍可用环境变量覆盖。
REM ---------------------------------------------------------------
setlocal
set "PROJECT_DIR=%~dp0..\"
set "AUTODETECT=%PROJECT_DIR%..\hwmcp\autodetect.py"

if not defined HYPERMESH_BATCH_EXE (
    for /f "usebackq delims=" %%P in (`python "%AUTODETECT%" --print hm_batch`) do set "HYPERMESH_BATCH_EXE=%%P"
)
if not defined HYPERMESH_GUI_EXE (
    for /f "usebackq delims=" %%P in (`python "%AUTODETECT%" --print hm_exe`) do set "HYPERMESH_GUI_EXE=%%P"
)

if not defined HYPERMESH_BATCH_EXE (
    echo ERROR: 未找到 hmbatch.exe
    echo 请设置 HYPERMESH_BATCH_EXE，或运行 python "%AUTODETECT%" 查看候选安装
    exit /b 1
)

echo hmbatch.exe = %HYPERMESH_BATCH_EXE%
python "%PROJECT_DIR%hypermesh_mcp_server.py"
