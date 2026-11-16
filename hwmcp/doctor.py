"""环境自检：接入 MCP 之前先跑这个，逐项确认能不能用。

    python doctor.py

只做只读检查 + 一次轻量建写测试（建 component、数一次实体），不改任何已有模型文件。
全程约 30-60 秒，其中大部分是 HyperMesh 启动时间。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import autodetect  # noqa: E402
import hm_session  # noqa: E402

OK = "[OK]"
BAD = "[!!]"
rows: list[tuple[bool, str, str]] = []


def check(name: str, cond, detail: str = "") -> bool:
    rows.append((bool(cond), name, detail))
    print(f"{OK if cond else BAD}  {name}" + (f"    {detail}" if detail else ""))
    return bool(cond)


def main() -> int:
    print("=" * 68)
    print("HyperMesh MCP 环境自检")
    print("=" * 68)

    # 1. Python
    v = sys.version_info
    check("Python 版本 >= 3.9", v >= (3, 9), f"当前 {v.major}.{v.minor}.{v.micro}  ({sys.executable})")

    # 2. 依赖包（应当为零依赖）
    try:
        import tools  # noqa: F401
        import hm_session  # noqa: F401

        check("服务端模块可导入", True, f"交互族工具数 {len(tools.TOOLS)}")
    except Exception as exc:  # noqa: BLE001
        check("服务端模块可导入", False, str(exc))
        return finish()

    # 3. HyperMesh 可执行文件（自动发现，多版本并存时列全）
    inst = autodetect.find_installations()
    exe = autodetect.find_hm_exe()
    if inst:
        listed = "、".join(f"{p.name}" for p in inst)
        check("发现 HyperMesh 安装", True, f"{len(inst)} 个：{listed}")
    else:
        check("发现 HyperMesh 安装", False,
              "注册表与常见目录都没找到含 hwdesktop/hm/bin/win64/hmopengl.exe 的安装")

    exe_ok = bool(exe) and Path(exe).exists()
    check("HyperMesh 可执行文件存在", exe_ok, exe or "未定位到")
    if not exe_ok:
        print("\n    处置（任选其一）：")
        print("      1) set HWMCP_HM_EXE=<安装根>\\hwdesktop\\hm\\bin\\win64\\hmopengl.exe")
        print("      2) set HWMCP_HM_VERSION=2021.2     # 多版本并存时指定用哪个")
        print("      3) set ALTAIR_HOME=<安装根>          # 如 D:\\Altair2021.2")
        return finish()
    check("用的是 GUI 版 hmopengl.exe（不是 hmbatch）",
          "hmbatch" not in Path(exe).name.lower(),
          f"{Path(exe).name}  @ {Path(exe).parents[4]}")

    # 4. 注入脚本
    sock_tcl = HERE / "_sock.tcl"
    check("注入脚本 _sock.tcl 存在", sock_tcl.exists(), str(sock_tcl))

    # 5. 端口可用
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        check("本机空闲端口可分配", True, f"示例端口 {port}")
    except OSError as exc:
        check("本机空闲端口可分配", False, str(exc))

    # 6. 实际拉起 HyperMesh
    print("\n-- 正在启动 HyperMesh，首次约 15-20 秒，请稍候 --")
    session = hm_session.HMSession()
    try:
        session.start(timeout=180)
        check("HyperMesh 进程启动并接受连接", True, f"端口 {session.port}")
    except Exception as exc:  # noqa: BLE001
        check("HyperMesh 进程启动并接受连接", False, str(exc))
        print("\n    处置：taskkill /F /IM hmopengl.exe 后重试；仍失败见 README 第 7 节")
        return finish()

    try:
        st = tools.t_status(session, {})
        check("求解器 profile 已加载", st.get("profile") == "OptiStruct",
              f"profile = {st.get('profile')}")
        if st.get("profile") != "OptiStruct":
            print("    处置：确认用的是 hmopengl.exe；batch 模式下 profile 恒为 HyperMesh")

        # 7. 轻量写测试：建 component 再数一次
        tools.t_new_model(session, {"component": "doctor_tmp"})
        n = tools.t_list_entities(session, {"entity_type": "comps"})
        written = any(e["name"] == "doctor_tmp" for e in n["entities"])
        check("可写入模型（建 component 成功）", written, f"当前 comps = {n['count']}")

        # 8. 网格入口可用（只建 1 块小平面，不划网格，省时间）
        s = tools.t_create_plane(session, {"size": 20})
        check("可建几何（平面曲面）", s.get("surfaces", 0) >= 1, f"surfaces = {s.get('surfaces')}")
    except Exception as exc:  # noqa: BLE001
        check("读写模型测试", False, str(exc))
    finally:
        session.stop()

    return finish()


def finish() -> int:
    print("\n" + "=" * 68)
    bad = [r for r in rows if not r[0]]
    if not bad:
        print("结论：全部通过，可以接入 MCP。")
        print("下一步：在仓库根目录跑")
        print("  python configure.py --write     # 自动生成并写入客户端 mcp.json")
        print("然后在客户端连接器列表里信任 hypermesh。")
        print("=" * 68)
        return 0
    print(f"结论：{len(bad)} 项未通过，先按提示处置再接入：")
    for _, name, detail in bad:
        print(f"  - {name}：{detail}")
    print("=" * 68)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
