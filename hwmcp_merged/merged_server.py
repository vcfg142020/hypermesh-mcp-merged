#!/usr/bin/env python
"""合并版 HyperMesh MCP Server（零依赖，stdio + JSON-RPC 2.0）。

把两套 HyperMesh MCP 合并到一个进程、一份工具表：

  交互族  hm_*   21 个  —— 常驻 GUI 会话（hmopengl.exe + socket 注入），
                          适合单模型的建模/网格/材料/工况/deck 导出。
  批处理族 其余  33 个  —— 每次起一个 hmbatch.exe 进程，
                          适合大批量零件过夜划分、探针分类、质量报告。

两族共享同一个 MCP 连接，但**执行通道相互独立**：交互族的模型状态常驻内存，
批处理族不碰 GUI 会话（除非显式调用 execute_tcl_gui 系列）。
因此不会出现「两个 GUI 抢 license」的情况 —— 整个进程最多一个 GUI。

用法
----
    python merged_server.py                 # stdio
    python merged_server.py --doctor        # 静态自检：还缺什么才能跑（<1 秒，不起 HyperMesh）
    python merged_server.py --list-tools    # 只打印工具表，便于核对
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
HWMP = HERE.parent / "hwmcp"
MESH = HERE.parent / "hm_mesh_mcp"

for path in (str(HERE), str(HWMP), str(MESH)):
    if path not in sys.path:
        sys.path.insert(0, path)

import tools as hm_tools  # noqa: E402  (hwmcp 的工具表)
from hm_session import HMError, HMSession  # noqa: E402
from mcp_shim import load_upstream  # noqa: E402
from schema import accepts, build_input_schema, first_doc_line  # noqa: E402

import autodetect  # noqa: E402

# 上游 hypermesh_mcp_server.py 的 hmbatch 候选表里只有 Altair 2020 的固定路径，
# 换机就找不到。这里用自动发现把结果写进环境变量（上游优先读 HYPERMESH_BATCH_EXE），
# 从而在不改动上游任何一行代码的前提下让它在本机可用。
if not os.environ.get("HYPERMESH_BATCH_EXE"):
    _batch = autodetect.find_hm_batch()
    if _batch:
        os.environ["HYPERMESH_BATCH_EXE"] = _batch
if not os.environ.get("HYPERMESH_GUI_EXE"):
    _gui = autodetect.find_hm_exe()
    if _gui:
        os.environ["HYPERMESH_GUI_EXE"] = _gui

SERVER_NAME = "hypermesh-mcp"
SERVER_VERSION = "1.0.0-merged"
PROTOCOL_FALLBACK = "2024-11-05"

_session: HMSession | None = None
_session_lock = threading.Lock()


def log(msg: str) -> None:
    print(f"[hwmcp-merged] {msg}", file=sys.stderr, flush=True)


def get_session() -> HMSession:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = HMSession()
    return _session


# ------------------------------------------------------------------ 工具表构建

def _build_mesh_specs() -> list[dict]:
    """从上游模块抽出 33 个工具，按签名生成 schema。"""
    upstream_py = MESH / "hypermesh_mcp_server.py"
    if not upstream_py.is_file():
        log(f"警告：未找到上游模块 {upstream_py}，批处理族将不可用")
        return []

    _module, functions = load_upstream(upstream_py)
    specs: list[dict] = []
    for fn in functions:
        doc = (fn.__doc__ or "").strip()
        specs.append({
            "name": fn.__name__,
            "description": f"[批处理/hmbatch] {first_doc_line(fn)}",
            "inputSchema": build_input_schema(fn),
            "impl": fn,
            "kind": "mesh",
            "long_doc": doc,
        })
    return specs


def _build_hm_specs() -> list[dict]:
    specs = []
    for spec in hm_tools.TOOLS:
        specs.append({
            **spec,
            "description": f"[交互/GUI 会话] {spec['description']}",
            "kind": "hm",
        })
    return specs


TOOLS: list[dict] = []
BY_NAME: dict[str, dict] = {}


def build_registry() -> None:
    global TOOLS, BY_NAME
    TOOLS = _build_hm_specs() + _build_mesh_specs()
    BY_NAME = {spec["name"]: spec for spec in TOOLS}
    dupes = len(TOOLS) - len(BY_NAME)
    if dupes:
        log(f"警告：存在 {dupes} 个重名工具，后者覆盖前者")
    log(f"工具注册完成：交互 {len(_build_hm_specs())} + 批处理 {len(TOOLS) - len(_build_hm_specs())} = {len(TOOLS)}")


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


def m_initialize(params: dict) -> dict:
    wanted = params.get("protocolVersion") or PROTOCOL_FALLBACK
    log(f"initialize from {params.get('clientInfo', {}).get('name', '?')} protocol={wanted}")
    return {
        "protocolVersion": wanted if isinstance(wanted, str) else PROTOCOL_FALLBACK,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "合并版 HyperMesh MCP：两种执行通道，一套连接。\n"
            "· hm_* （交互族，常驻 GUI 会话）：hm_new_model → hm_create_plane_surface | hm_open_model "
            "→ hm_mesh_surfaces → hm_create_material → hm_create_property → hm_assign_property "
            "→ hm_add_constraints / hm_add_force → hm_create_loadstep → hm_export。"
            "首次调用会拉起 HyperMesh GUI（约 15-25 秒），之后毫秒级。\n"
            "· generate_* / classify_* / execute_tcl （批处理族，每次起 hmbatch 进程）："
            "generate_geometry_probe_tcl → classify_all_solids_from_probe → generate_phase2_finalize_tcl "
            "→ generate_*_hex/tetra → execute_tcl。原始网格命令被白名单拦截，必须用生成器。\n"
            "两族互不干扰，但同一时刻只应有一个 HyperMesh GUI 进程。"
        ),
    }


def m_tools_list() -> dict:
    return {"tools": [{"name": s["name"], "description": s["description"],
                       "inputSchema": s["inputSchema"]} for s in TOOLS]}


def _batch_call(spec: dict, args: dict) -> object:
    """批处理族调用：临时摘掉 HW_CONFIG_PATH。

    本机 HW_CONFIG_PATH 指向自定义 GUI 配置（含 views\\mymodelview）。
    hmbatch 启动时会执行 ``hm_framework getpulldowns``，该命令在 batch 模式下非法，
    直接导致 ``Invalid args to hm_framework (batch mode)``、returncode=1、脚本从不执行。
    清空该变量后 hmbatch 正常（实测 puts 有输出）。GUI 会话仍需要它，故只在批处理期间摘除。
    """
    saved = os.environ.pop("HW_CONFIG_PATH", None)
    try:
        return _normalize_batch_result(spec["impl"](**args))
    finally:
        if saved is not None:
            os.environ["HW_CONFIG_PATH"] = saved


def _normalize_batch_result(result: object) -> object:
    """修正 hmbatch 退出码语义造成的假失败。

    实测（2021.2）：``hmbatch -tcl <file>`` 的进程退出码等于**脚本最后一条命令的
    返回值**，不等于是否出错。``set n 1`` → 退出码 1；``set n 0`` / ``puts x`` → 0；
    显式 ``exit 0`` 也压不住。于是上游 ``success = returncode == 0`` 会把跑成功的
    脚本判成失败（stdout 里明明有输出、有 "End of command file - terminating."）。

    这里只在**确证脚本已跑完且无 Tcl 错误**时才改判，并保留 ``raw_returncode``
    与说明字段，不隐藏任何信息。
    """
    if not isinstance(result, dict):
        return result
    rc = result.get("returncode")
    if not isinstance(rc, int) or rc == 0:
        return result
    out = str(result.get("stdout") or "")
    if "Tcl/Tk script error" in out:
        return result
    if "End of command file - terminating." not in out:
        return result

    result["raw_returncode"] = rc
    result["success"] = True
    result["returncode"] = 0
    result["success_note"] = (
        f"hmbatch 原始退出码 {rc}，等于脚本最后一条 Tcl 命令的返回值，"
        "并非执行失败：stdout 无 Tcl 错误且已到 “End of command file”。"
        "如需退出码恒为 0，在脚本末尾追加 `set __mcp_rc 0`。"
    )
    return result


def m_tools_call(params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    spec = BY_NAME.get(name)
    if spec is None:
        return text_result(f"未知工具：{name}", is_error=True)

    started = time.perf_counter()
    try:
        if spec["kind"] == "hm":
            result = spec["impl"](get_session(), args)
        else:
            ok, why = accepts(spec["impl"], args)
            if not ok:
                return text_result(f"参数不匹配：{why}", is_error=True)
            result = _batch_call(spec, args)
        elapsed = (time.perf_counter() - started) * 1000
        if elapsed > 3000:
            log(f"{name} 耗时 {elapsed/1000:.1f}s")
        return text_result(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except HMError as exc:
        return text_result(f"HyperMesh 报错：{exc}", is_error=True)
    except KeyError as exc:
        return text_result(f"缺少参数：{exc}", is_error=True)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        return text_result(f"工具执行异常：{type(exc).__name__}: {exc}", is_error=True)


def handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    if method is None:
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
    try:
        get_session().start(timeout=float(os.environ.get("HWMCP_STARTUP_TIMEOUT", "180")))
        log(f"HyperMesh ready on port {_session.port if _session else '?'}")
    except Exception as exc:  # noqa: BLE001
        log(f"预启动失败（将在首次调用时重试）：{exc}")


def _doctor() -> int:
    """不连 MCP、不起 HyperMesh 的快速自检：只回答「还缺什么才能跑」。

    与 hwmcp/doctor.py 的分工：doctor.py 会真起一次 HyperMesh 做读写测试（30-60 秒），
    这里只做静态检查（<1 秒），适合放进 CI 或作为 clone 后的第一道门。
    """
    import autodetect

    print("=" * 72)
    print("hypermesh-mcp 环境自检（静态）")
    print("=" * 72)
    info = autodetect.describe()
    ok = True

    def row(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        # 中文字符占两列，按显示宽度补空格，否则标签列参差不齐
        width = sum(2 if ord(ch) > 0x2E80 else 1 for ch in label)
        print(f"{'[OK]' if good else '[!!]'}  {label}{' ' * max(0, 34 - width)}  {detail}".rstrip())

    v = sys.version_info
    row(v >= (3, 9), "Python >= 3.9", f"{info['python_version']}  {info['python']}")

    third = []
    for mod in ("pydantic", "mcp"):
        try:
            __import__(mod)
            third.append(mod)
        except ImportError:
            pass
    row(not third, "零第三方依赖", f"（运行时可见：{third}）" if third else "mcp 由内置 mcp_shim 提供")

    row(Path(__file__).with_name("mcp_shim.py").is_file(), "mcp_shim.py 在位")
    row((HERE.parent / "hwmcp" / "_sock.tcl").is_file(), "hwmcp/_sock.tcl 在位")

    row(bool(info["hm_exe"]), "HyperMesh hmopengl.exe", info["hm_exe"] or "未定位到")
    if info["installations"]:
        print(f"     候选安装：{', '.join(i['root'] for i in info['installations'])}")
        if len(info["installations"]) > 1:
            print("     多版本并存，默认取最高版本；用 HWMCP_HM_VERSION=2021.2 可锁定")
    row(bool(info["hm_batch"]), "hmbatch.exe（批处理族）", info["hm_batch"] or "未定位到")

    if info["hw_config_path"]:
        print(f"[..]  HW_CONFIG_PATH 已设置，批处理族调用时会临时摘除")
        print(f"      {info['hw_config_path']}")

    try:
        build_registry()
        hm_n = sum(1 for s in TOOLS if s["kind"] == "hm")
        row(len(TOOLS) >= 50, "工具表构建成功", f"共 {len(TOOLS)} 个（交互 {hm_n} / 批处理 {len(TOOLS)-hm_n}）")
    except Exception as exc:  # noqa: BLE001
        row(False, "工具表构建成功", f"{type(exc).__name__}: {exc}")

    print("=" * 72)
    if ok:
        print(f"结论：静态检查全部通过。下一步跑 python {HERE.parent / 'hwmcp' / 'doctor.py'} 做真启动验证。")
        return 0
    print(f"结论：有项目未通过，按上面提示处置。也可跑 python {HERE.parent / 'hwmcp' / 'doctor.py'} 看更详细的处置建议。")
    return 1


def main() -> None:
    if "--doctor" in sys.argv or "--self-check" in sys.argv:
        raise SystemExit(_doctor())

    if "--list-tools" in sys.argv:
        build_registry()
        for spec in TOOLS:
            kind = "hm " if spec["kind"] == "hm" else "mesh"
            print(f"{kind}  {spec['name']:44s} {spec['description'][:60]}")
        print(f"\n合计 {len(TOOLS)} 个工具")
        return

    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    log(f"started, python={sys.version.split()[0]}")
    build_registry()

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
