#!/usr/bin/env python
"""一条命令生成 MCP 客户端配置（零依赖）。

它做三件事：
    1. 自动发现 python 解释器与本机 HyperMesh 安装
    2. 生成可直接粘贴/写入的 mcp.json 片段
    3. 可选地直接写进客户端配置文件（--write），写入前自动备份

用法
----
    python configure.py                      # 只打印，不改任何文件
    python configure.py --version 2021.2     # 锁版本
    python configure.py --write              # 自动找客户端配置并写入
    python configure.py --write <path.json>  # 写入指定文件
    python configure.py --json               # 只输出纯 JSON，便于脚本消费
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "hwmcp"))

import autodetect  # noqa: E402

SERVER = ROOT / "hwmcp_merged" / "merged_server.py"

CLIENT_CANDIDATES = [
    ("WorkBuddy", Path.home() / ".workbuddy" / "mcp.json"),
    ("Claude Desktop", Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"),
    ("Cursor", Path.home() / ".cursor" / "mcp.json"),
]


def build_entry(version: str | None) -> dict:
    entry: dict = {
        "command": autodetect.find_python(),
        "args": [str(SERVER)],
        "env": {"HWMCP_AUTOSTART": "1"},
    }
    exe = autodetect.find_hm_exe(version)
    if exe:
        # 优先写可读性好、换机也不会错的版本号；退而求其次才写绝对路径。
        # 安装根 = <root>/hwdesktop/hm/bin/win64/hmopengl.exe 往上四级。
        root = Path(exe).parents[4]
        ver = "".join(ch for ch in root.name if ch.isdigit() or ch == ".")
        if ver and ver.replace(".", "").isdigit():
            entry["env"]["HWMCP_HM_VERSION"] = ver
        else:
            entry["env"]["HWMCP_HM_EXE"] = exe
    return entry


def find_client_config() -> tuple[str, Path] | None:
    for name, p in CLIENT_CANDIDATES:
        if p and p.is_file():
            return name, p
    return None


def write_config(path: Path, entry: dict) -> None:
    if path.is_file():
        backup = path.with_suffix(path.suffix + f".bak.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"已备份原配置 -> {backup}")
        raw = path.read_text(encoding="utf-8-sig")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            sys.exit(f"目标文件不是合法 JSON，已中止以免覆盖：{exc}")
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    replaced = "hypermesh" in servers
    servers["hypermesh"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"已{'更新' if replaced else '写入'} mcpServers.hypermesh -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 HyperMesh MCP 客户端配置")
    ap.add_argument("--version", help="锁定 HyperWorks 版本，如 2021.2（多版本并存时用）")
    ap.add_argument("--write", nargs="?", const="", metavar="PATH", help="写入客户端配置（省略路径则自动查找）")
    ap.add_argument("--json", action="store_true", help="只输出纯 JSON")
    args = ap.parse_args()

    entry = build_entry(args.version)

    if args.json:
        print(json.dumps({"mcpServers": {"hypermesh": entry}}, indent=2, ensure_ascii=False))
        return 0

    info = autodetect.describe()
    if args.version:
        # 抬头显示的应当是「实际会被使用的那个」，而不是自动发现的最高版本
        info["hm_exe"] = autodetect.find_hm_exe(args.version)
        info["hm_batch"] = autodetect.find_hm_batch(info["hm_exe"])
    if not args.json:
        print("=" * 72)
        print("环境探测结果")
        print("=" * 72)
        print(f"  Python       {info['python']}")
        print(f"  HyperMesh    {info['hm_exe'] or '未定位到'}")
        print(f"  hmbatch      {info['hm_batch'] or '未定位到'}")
        if len(info["installations"]) > 1:
            print(f"  多版本并存    {', '.join(i['root'] for i in info['installations'])}")
            print("               默认取最高版本；用 --version 2021.2 可锁定")
        if not info["hm_exe"]:
            print("\n  警告：未找到 HyperMesh。仍会生成配置，但运行时需要设置 HWMCP_HM_EXE。")
        print()

    snippet = json.dumps({"mcpServers": {"hypermesh": entry}}, indent=2, ensure_ascii=False)
    print("生成的客户端配置：")
    print(snippet)

    if args.write is None:
        print("\n把上面这段合并进客户端的 mcp.json 即可；也可加 --write 让本脚本代写。")
        return 0 if info["hm_exe"] else 1

    if args.write == "":
        found = find_client_config()
        if not found:
            print("\n没找到已知客户端配置文件。请显式传入路径：python configure.py --write <path/to/mcp.json>")
            return 1
        name, path = found
        print(f"\n检测到 {name} 配置：{path}")
    else:
        path = Path(args.write).expanduser()

    write_config(path, entry)
    print("\n下一步：重启客户端，在连接器列表里信任 hypermesh。")
    print("验证：python hwmcp/doctor.py   （会真启动一次 HyperMesh，约 30-60 秒）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
