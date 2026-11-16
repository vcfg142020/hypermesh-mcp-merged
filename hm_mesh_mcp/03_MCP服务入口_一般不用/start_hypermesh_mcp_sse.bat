@echo off
REM ---------------------------------------------------------------
REM  HyperMesh MCP - SSE 启动（旧入口，一般用不到）
REM  原脚本写死了 C:\Program Files\Altair\2020\..., 换机必失效。
REM  改为调用 hwmcp/autodetect.py 自动发现。
REM ---------------------------------------------------------------
setlocal
set "PROJECT_DIR=%~dp0..\"
set "AUTODETECT=%PROJECT_DIR%..\hwmcp\autodetect.py"

if not defined HYPERMESH_BATCH_EXE (
    for /f "usebackq delims=" %%P in (`python "%AUTODETECT%" --print hm_batch`) do set "HYPERMESH_BATCH_EXE=%%P"
)

if not defined HYPERMESH_BATCH_EXE (
    echo ERROR: 未找到 hmbatch.exe
    echo 请设置 HYPERMESH_BATCH_EXE，或运行 python "%AUTODETECT%" 查看候选安装
    exit /b 1
)

echo Starting HyperMesh MCP Server in SSE mode on http://127.0.0.1:8742/sse
echo Keep this window open while using the client.
echo Press Ctrl+C to stop.
echo.
python "%PROJECT_DIR%hypermesh_mcp_server.py" --transport sse --host 127.0.0.1 --port 8742
pause
