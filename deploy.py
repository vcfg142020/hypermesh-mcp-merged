#!/usr/bin/env python
"""一键部署：探测环境 → 静态自检 → 生成并写入客户端配置 →（可选）真启动验证。

设计目标：在一台**新机器**上，`git clone` 之后只跑这一条命令就完成部署。
脚本幂等——重复运行不会重复备份，也不会改坏已有配置。

用法
----
    python deploy.py                     # 全自动：探测 → 自检 → 写配置
    python deploy.py --version 2021.2    # 多版本并存时锁定版本
    python deploy.py --client claude     # 指定客户端（workbuddy / claude / cursor / <路径>）
    python deploy.py --dry-run           # 只看探测结果，不写任何文件
    python deploy.py --verify            # 额外真启动一次 HyperMesh（30-60 秒，占 1 个 license）
    python deploy.py --json              # 输出机器可读结果（给 AI 或 CI 用）

退出码：0 = 部署完成；1 = 有阻塞项，脚本会指出怎么修。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "hwmcp"))
sys.path.insert(0, str(ROOT))

import autodetect  # noqa: E402
import configure as cfg  # noqa: E402

SERVER = ROOT / "hwmcp_merged" / "merged_server.py"
HM_DOCTOR = ROOT / "hwmcp" / "doctor.py"
MIN_PY = (3, 9)

# 缺任何一个都跑不起来。顺序按依赖链排，便于定位「缺在哪一层」。
REQUIRED = [
    ("configure.py", "配置生成器"),
    ("hwmcp/autodetect.py", "安装位置自动发现"),
    ("hwmcp/hm_session.py", "交互族会话"),
    ("hwmcp/_sock.tcl", "注入 HyperMesh 的 socket 服务"),
    ("hwmcp/tools.py", "交互族工具实现"),
    ("hwmcp_merged/merged_server.py", "MCP 服务入口"),
    ("hwmcp_merged/mcp_shim.py", "假 mcp 模块（零改动加载 FastMCP）"),
    ("hwmcp_merged/schema.py", "函数签名 → JSON Schema"),
    ("hm_mesh_mcp/hypermesh_mcp_server.py", "批处理族上游"),
]

CLIENTS = {
    "workbuddy": Path.home() / ".workbuddy" / "mcp.json",
    "claude": Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
    "cursor": Path.home() / ".cursor" / "mcp.json",
}

CLIENT_LABEL = {"workbuddy": "WorkBuddy", "claude": "Claude Desktop", "cursor": "Cursor"}


def cjk_width(s: str) -> int:
    """终端里中文占两列，按显示宽度补空格才对得齐。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


class Report:
    """同时服务于人类可读输出和 --json 机器输出。"""

    def __init__(self, quiet: bool) -> None:
        self.quiet = quiet
        self.steps: list[dict] = []
        self.notes: list[str] = []
        self.next_steps: list[str] = []

    def title(self, text: str) -> None:
        if self.quiet:
            return
        print("=" * 74)
        print(text)
        print("=" * 74)

    def add(self, ok: bool | None, label: str, detail: str = "") -> None:
        self.steps.append({"check": label, "ok": ok, "detail": detail})
        if self.quiet:
            return
        mark = {True: "OK  ", False: "!!  ", None: "..  "}[ok]
        pad = " " * max(0, 30 - cjk_width(label))
        print(f"[{mark}] {label}{pad} {detail}".rstrip())

    def note(self, text: str) -> None:
        self.notes.append(text)
        if self.quiet:
            return
        for line in text.splitlines():
            print("      " + line)

    def blocked(self) -> list[dict]:
        return [s for s in self.steps if s["ok"] is False]

    def as_dict(self, **extra) -> dict:
        return {
            "ok": not self.blocked(),
            "root": str(ROOT),
            "steps": self.steps,
            "notes": self.notes,
            "next": self.next_steps,
            **extra,
        }


def same_entry(path: Path, entry: dict) -> bool:
    """配置已经就是我们要写的样子时，跳过写入——避免每次部署都堆一个 .bak。"""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return (data.get("mcpServers") or {}).get("hypermesh") == entry


def resolve_client(spec: str | None) -> tuple[str, Path]:
    if spec:
        low = spec.lower()
        if low in CLIENTS:
            return CLIENT_LABEL[low], CLIENTS[low]
        return "自定义路径", Path(os.path.expanduser(spec))
    found = cfg.find_client_config()
    if found:
        return found[0], found[1]
    return "WorkBuddy（新建）", CLIENTS["workbuddy"]


def run_doctor(env: dict, quiet: bool) -> tuple[bool, str]:
    cmd = [sys.executable, str(SERVER), "--doctor"]
    if quiet:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        return (r.returncode == 0 and "[!!]" not in out), out.strip().splitlines()[-1] if out.strip() else ""
    r = subprocess.run(cmd, env=env)
    return r.returncode == 0, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="HyperMesh MCP 一键部署")
    ap.add_argument("--version", help="锁定 HyperWorks 版本，如 2021.2（多版本并存时用）")
    ap.add_argument("--client", help="目标客户端：workbuddy / claude / cursor / <json 路径>")
    ap.add_argument("--dry-run", action="store_true", help="只探测，不写配置")
    ap.add_argument("--verify", action="store_true", help="额外真启动一次 HyperMesh（30-60 秒）")
    ap.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    args = ap.parse_args()

    rep = Report(quiet=args.json)
    env = dict(os.environ)
    if args.version:
        env["HWMCP_HM_VERSION"] = args.version        # 让子进程与配置保持一致
    if not args.json:
        print()

    rep.title("HyperMesh MCP 部署")

    # 1) Python：脚本自身已在跑，这里只拦版本过低
    ver = ".".join(str(x) for x in sys.version_info[:3])
    rep.add(sys.version_info >= MIN_PY, f"Python >= {'.'.join(map(str, MIN_PY))}",
            f"{ver}  {sys.executable}")

    # 2) 仓库完整性：clone 不全或用了 git archive 少了文件，都能在这里暴露
    missing = [rel for rel, _ in REQUIRED if not (ROOT / rel).is_file()]
    rep.add(not missing, "仓库文件完整",
            f"{len(REQUIRED)} 项齐备" if not missing else f"缺少：{', '.join(missing)}")

    # 3) 第三方依赖：能 import 就说明没额外依赖（mcp 由 shim 提供）
    rep.add(True, "零第三方依赖", "无需 pip install（含 mcp 包）")

    # 4) HyperMesh 探测
    installations = autodetect.find_installations()
    exe = autodetect.find_hm_exe(args.version)
    batch = autodetect.find_hm_batch(exe) if exe else None

    if exe:
        root = Path(exe).parents[4]
        rep.add(True, "HyperMesh hmopengl.exe", f"{root.name}  ({exe})")
    else:
        rep.add(False, "HyperMesh hmopengl.exe", "未找到")
        rep.note(
            "未定位到 HyperMesh。三种处置，任选其一：\n"
            "  1) set HWMCP_HM_EXE=<安装根>\\hwdesktop\\hm\\bin\\win64\\hmopengl.exe\n"
            "  2) set HWMCP_HM_VERSION=2021.2      # 多版本并存时指定用哪个\n"
            "  3) set ALTAIR_HOME=<安装根>           # 如 D:\\Altair2021.2\n"
            "若安装目录名不含 \"Altair\"，只能用第 1 种。")
    rep.add(bool(batch), "hmbatch.exe（批处理族）", batch or "未找到")

    if len(installations) > 1:
        rep.note(f"检测到 {len(installations)} 个安装：{'、'.join(p.name for p in installations)}\n"
                 f"当前使用 {'锁定版本 ' + args.version if args.version else '最高版本'}；"
                 "要换版本就加 --version")

    # 5) 静态自检（等价于别人 clone 后第一次跑的那条命令）
    if exe:
        ok, tail = run_doctor(env, args.json)
        rep.add(ok, "服务静态自检（--doctor）", tail)

    # 6) 生成并写入客户端配置
    entry = cfg.build_entry(args.version)
    label, target = resolve_client(args.client)
    rep.add(True, "客户端配置", f"{label} → {target}")
    rep.note("env: " + json.dumps(entry.get("env", {}), ensure_ascii=False) +
             ("   （写的是版本号，不是绝对路径，可跨机器复用）"
              if "HWMCP_HM_VERSION" in entry.get("env", {}) else ""))

    wrote = False
    if args.dry_run:
        rep.note("--dry-run：未写入任何文件。")
    elif same_entry(target, entry):
        rep.note("配置已是最新，跳过写入（未产生备份文件）。")
    else:
        try:
            if args.json:
                # configure.write_config 会 print 人类可读信息，--json 时必须吞掉，
                # 否则 stdout 混入非 JSON 文本，调用方解析失败。
                import contextlib
                import io

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    cfg.write_config(target, entry)
                rep.notes.extend(x for x in buf.getvalue().strip().splitlines() if x)
            else:
                cfg.write_config(target, entry)
            wrote = True
        except SystemExit as exc:                      # configure 用 sys.exit 报错
            rep.add(False, "写入客户端配置", str(exc))
        except OSError as exc:
            rep.add(False, "写入客户端配置", f"{type(exc).__name__}: {exc}")

    # 7) 可选：真启动一次 HyperMesh
    if args.verify and exe:
        if not args.json:
            print("\n正在真启动 HyperMesh 做读写测试（30-60 秒）...\n")
        r = subprocess.run([sys.executable, str(HM_DOCTOR)], env=env,
                           capture_output=args.json, text=True,
                           encoding="utf-8", errors="replace")
        ok = r.returncode == 0
        tail = ""
        if args.json:
            out = (r.stdout or "") + (r.stderr or "")
            tail = next((l for l in reversed(out.strip().splitlines()) if l.strip()), "")
        rep.add(ok, "真启动验证（hwmcp/doctor.py）", tail)

    # 结论
    blocked = rep.blocked()
    rep.next_steps = [
        "重启客户端（WorkBuddy / Claude Desktop），让新的 mcp.json 生效",
        "连接器列表里若出现 hypermesh，点击信任",
        "可选：python hwmcp/doctor.py  真启动一次确认（30-60 秒）",
    ] if not blocked else ["先解决上面标 [!!] 的项，再重新运行 python deploy.py"]

    if args.json:
        print(json.dumps(rep.as_dict(client={"name": label, "path": str(target)},
                                     written=wrote, dry_run=args.dry_run),
                         ensure_ascii=False, indent=2))
    else:
        print()
        print("=" * 74)
        if blocked:
            print(f"结论：有 {len(blocked)} 个阻塞项，部署未完成。")
        elif args.dry_run:
            print("结论：环境可用（dry-run，未写配置）。去掉 --dry-run 即可落盘。")
        else:
            print("结论：部署完成。")
        for i, s in enumerate(rep.next_steps, 1):
            print(f"  {i}. {s}")
        print("=" * 74)
        if not blocked and not args.dry_run:
            print("\n配置内容（已写入，无需手工编辑）：")
            print(json.dumps({"mcpServers": {"hypermesh": entry}}, ensure_ascii=False, indent=2))

    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
