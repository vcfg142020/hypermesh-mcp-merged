"""把 hm_mesh_mcp 的上游模块装进零依赖运行时。

上游 `hypermesh_mcp_server.py` 顶部 `from mcp.server.fastmcp import FastMCP`，
只用 FastMCP 做两件事：注册工具（装饰器）和跑服务（`mcp.run()`）。
本 shim 提供最小替身，使该模块可在 **不安装 mcp 包** 的解释器里被 import，
从而复用它的 33 个工具实现，且**不修改上游一行代码**。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Callable


class _FakeFastMCP:
    """只记录被 @mcp.tool() 装饰的函数，不实现协议。"""

    def __init__(self, name: str = "fake", **_: Any) -> None:
        self.name = name
        self.registered: list[Callable[..., Any]] = []
        self.settings = types.SimpleNamespace(host="127.0.0.1", port=0)

    def tool(self, *_args: Any, **_kwargs: Any):
        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.registered.append(fn)
            return fn

        return decorate

    def run(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        raise RuntimeError("shim 模式不支持直接运行，请用 merged_server.py")

    def mount(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        pass


def _install_fake_mcp() -> None:
    """在 sys.modules 里铺出 mcp / mcp.server / mcp.server.fastmcp 三层。"""
    if "mcp.server.fastmcp" in sys.modules:
        return

    mcp = types.ModuleType("mcp")
    mcp.__path__ = []  # type: ignore[attr-defined]
    server = types.ModuleType("mcp.server")
    server.__path__ = []  # type: ignore[attr-defined]
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = _FakeFastMCP  # type: ignore[attr-defined]

    sys.modules["mcp"] = mcp
    sys.modules["mcp.server"] = server
    sys.modules["mcp.server.fastmcp"] = fastmcp


def load_upstream(server_py: Path) -> tuple[Any, list[Callable[..., Any]]]:
    """加载上游模块，返回 (module, 已注册工具函数列表)。"""
    _install_fake_mcp()

    module_name = "hm_mesh_upstream"
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        return mod, list(getattr(mod.mcp, "registered", []))

    spec = importlib.util.spec_from_file_location(module_name, str(server_py))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载上游模块：{server_py}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)

    registered = list(getattr(getattr(mod, "mcp", None), "registered", []))
    return mod, registered
