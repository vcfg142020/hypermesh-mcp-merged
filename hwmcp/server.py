#!/usr/bin/env python
"""HyperMesh MCP Server（零依赖，stdio + JSON-RPC 2.0）。

让 AI 通过标准 MCP 协议驱动 HyperMesh 完成前处理：建几何、划网格、
赋材料属性、加约束载荷、建工况、导出求解器 deck。

用法
----
    python server.py

MCP 客户端配置（Claude Desktop / WorkBuddy 等）：

    {
      "mcpServers": {
        "hypermesh": {
          "command": "python",
          "args": ["F:/Program/WorkbuddyFiles/hyperworks/hwmcp/server.py"],
          "env": {"HWMCP_HM_EXE": "F:/Program/Altair2021.2/hwdesktop/hm/bin/win64/hmopengl.exe"}
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback

import tools
from hm_session import HMError, HMSession

SERVER_NAME = "hypermesh-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_FALLBACK = "2024-11-05"

_session: HMSession | None = None
_session_lock = threading.Lock()


def get_session() -> HMSession:
    """单例会话。必须加锁——后台预热线程与工具调用可能同时走到这里。"""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = HMSession()
    return _session


def log(msg: str) -> None:
    print(f"[hwmcp] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ JSON-RPC

def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(req_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def reply_error(req_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ------------------------------------------------------------------ 方法实现

def m_initialize(params: dict) -> dict:
    wanted = params.get("protocolVersion") or PROTOCOL_FALLBACK
    log(f"initialize from {params.get('clientInfo', {}).get('name', '?')} protocol={wanted}")
    return {
        "protocolVersion": wanted if isinstance(wanted, str) else PROTOCOL_FALLBACK,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "这是驱动 Altair HyperMesh 2021.2 做前处理的 MCP。"
            "典型流程：hm_new_model → (hm_create_plane_surface | hm_open_model) → hm_mesh_surfaces "
            "→ hm_create_material → hm_create_property → hm_assign_property "
            "→ hm_add_constraints / hm_add_force → hm_create_loadstep → hm_export。"
            "首次调用会自动启动 HyperMesh（GUI 版，约 15-20 秒）。"
            "未覆盖的操作可用 hm_run_tcl 直接执行 Tcl。"
        ),
    }


def m_tools_list() -> dict:
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in tools.TOOLS
        ]
    }


def m_tools_call(params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    spec = tools.BY_NAME.get(name)
    if spec is None:
        return text_result(f"未知工具：{name}", is_error=True)

    session = get_session()
    try:
        result = spec["impl"](session, args)
        return text_result(json.dumps(result, ensure_ascii=False, indent=2))
    except HMError as exc:
        return text_result(f"HyperMesh 报错：{exc}", is_error=True)
    except KeyError as exc:
        return text_result(f"缺少参数：{exc}", is_error=True)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        return text_result(f"工具执行异常：{type(exc).__name__}: {exc}", is_error=True)


# ------------------------------------------------------------------ 主循环

def handle(msg: dict):
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method is None:  # 客户端发来的响应，忽略
        return

    is_notification = "id" not in msg

    try:
        if method == "initialize":
            reply(req_id, m_initialize(params))
        elif method in ("notifications/initialized", "notifications/cancelled"):
            return
        elif method == "ping":
            reply(req_id, {})
        elif method == "tools/list":
            reply(req_id, m_tools_list())
        elif method == "tools/call":
            reply(req_id, m_tools_call(params))
        elif method == "resources/list":
            reply(req_id, {"resources": []})
        elif method == "prompts/list":
            reply(req_id, {"prompts": []})
        elif method == "logging/setLevel":
            reply(req_id, {})
        else:
            if not is_notification:
                reply_error(req_id, -32601, f"未实现的方法：{method}")
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        if not is_notification:
            reply_error(req_id, -32603, f"内部错误：{exc}")


def _prestart_hypermesh() -> None:
    """后台预热 HyperMesh。

    必须放在线程里：HyperMesh 启动要 15-20 秒，若在进入 stdin 读取循环前同步等待，
    客户端发 initialize 时无人应答，会直接判定 "MCP error -32000: Connection closed"。
    """
    try:
        get_session().start(timeout=float(os.environ.get("HWMCP_STARTUP_TIMEOUT", "180")))
        log(f"HyperMesh ready on port {_session.port if _session else '?'}")
    except Exception as exc:  # noqa: BLE001
        log(f"预启动失败（将在首次调用时重试）：{exc}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    log(f"started, python={sys.version.split()[0]}")
    if os.environ.get("HWMCP_AUTOSTART", "1") == "1":
        threading.Thread(target=_prestart_hypermesh, name="hwmcp-prestart", daemon=True).start()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log(f"非法 JSON：{line[:200]}")
            continue
        if isinstance(msg, list):
            for item in msg:
                handle(item)
        else:
            handle(msg)


if __name__ == "__main__":
    try:
        main()
    finally:
        if _session is not None:
            _session.stop()
