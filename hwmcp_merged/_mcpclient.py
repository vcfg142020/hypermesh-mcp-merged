"""极简 MCP stdio 客户端，供 verify_tools.py 使用。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

PY = r"C:/Users/2025057553/.workbuddy/binaries/python/versions/3.13.12/python.exe"
SERVER = str((__import__("pathlib").Path(__file__).resolve().parent / "merged_server.py"))
# 与客户端 mcp.json 保持一致：必须是 hmopengl.exe（GUI 版），否则 profile 不是 OptiStruct
HM_EXE = r"F:/Program/Altair2021.2/hwdesktop/hm/bin/win64/hmopengl.exe"


class MCPClient:
    def __init__(self, autostart: bool = False, extra_env: dict[str, str] | None = None):
        env = dict(os.environ)
        env["HWMCP_AUTOSTART"] = "1" if autostart else "0"
        env.setdefault("HWMCP_HM_EXE", HM_EXE)
        env.setdefault("PYTHONUTF8", "1")
        if extra_env:
            env.update(extra_env)
        self.proc = subprocess.Popen(
            [PY, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
        )
        self.stderr: list[str] = []
        self._pending: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        threading.Thread(target=self._drain_err, daemon=True).start()
        threading.Thread(target=self._drain_out, daemon=True).start()

    # -- io ---------------------------------------------------------------
    def _drain_err(self) -> None:
        for line in self.proc.stderr:  # type: ignore[union-attr]
            self.stderr.append(line.rstrip())

    def _drain_out(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                self._pending[msg.get("id")] = msg

    def _send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def _wait(self, rid: int, timeout: float) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self._pending:
                    return self._pending.pop(rid)
            if self.proc.poll() is not None:
                return None
            time.sleep(0.02)
        return None

    # -- api --------------------------------------------------------------
    def initialize(self, timeout: float = 30) -> tuple[dict, float]:
        self._next_id += 1
        rid = self._next_id
        t0 = time.perf_counter()
        self._send({"jsonrpc": "2.0", "id": rid, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "verify", "version": "1"}}})
        msg = self._wait(rid, timeout)
        elapsed = time.perf_counter() - t0
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return (msg or {}), elapsed

    def list_tools(self, timeout: float = 30) -> list[dict]:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": "tools/list", "params": {}})
        msg = self._wait(rid, timeout) or {}
        return msg.get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict | None = None,
             timeout: float = 300) -> tuple[Any, bool, float, str]:
        """返回 (payload, is_error, 耗时秒, 原始文本)。"""
        self._next_id += 1
        rid = self._next_id
        t0 = time.perf_counter()
        self._send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}}})
        msg = self._wait(rid, timeout)
        elapsed = time.perf_counter() - t0
        if msg is None:
            return None, True, elapsed, "（超时或进程退出）"
        if "error" in msg:
            return None, True, elapsed, str(msg["error"])
        result = msg.get("result", {})
        is_error = bool(result.get("isError"))
        text = ""
        content = result.get("content") or []
        if content and isinstance(content, list):
            text = content[0].get("text", "")
        payload: Any = text
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        return payload, is_error, elapsed, text

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    c = MCPClient(autostart=False)
    init, dt = c.initialize()
    print("initialize", f"{dt*1000:.0f}ms", init.get("result", {}).get("serverInfo"))
    tools = c.list_tools()
    print("tools:", len(tools))
    for name, args in [("get_meshing_rules", {}), ("hm_deck_report", {"path": ""})]:
        payload, err, el, text = c.call(name, args)
        print(name, "err=", err, f"{el*1000:.0f}ms", str(payload)[:160].replace("\n", " "))
    c.close()
    sys.exit(0)
