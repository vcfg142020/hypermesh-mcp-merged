@echo off
REM ---------------------------------------------------------------
REM HyperMesh Meshing MCP - stdio launcher
REM Registrable directly as a WorkBuddy / Codex MCP "command".
REM ---------------------------------------------------------------
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo ERROR: venv not found at "%PY%"
    echo Run: python -m venv .venv  and install requirements.lock.txt
    exit /b 1
)

REM Optional overrides. Leave blank to use hypermesh_batch_path.txt
if not defined HYPERMESH_BATCH_EXE (
    if exist "%ROOT%hypermesh_batch_path.txt" (
        for /f "usebackq delims=" %%L in ("%ROOT%hypermesh_batch_path.txt") do (
            if not "%%L"=="" set "HYPERMESH_BATCH_EXE=%%L"
        )
    )
)

cd /d "%ROOT%"
"%PY%" "%ROOT%hypermesh_mcp_server.py" --transport stdio %*
