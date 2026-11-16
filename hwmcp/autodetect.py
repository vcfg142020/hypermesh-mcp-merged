"""HyperMesh / Python 安装位置自动发现（零依赖，仅标准库）。

为什么要这个模块
----------------
把仓库 push 到 GitHub 之后再 ``git clone`` 到另一台机器，写死的
``<某个固定盘符>/Altair2021.2/.../hmopengl.exe`` 必然失效。这里按优先级逐级探测，
让「复制下来直接用」在不改任何代码的前提下成立：

    1. 环境变量 HWMCP_HM_EXE        —— 显式指定，最高优先级，也是唯一的官方覆盖口
    2. 环境变量 ALTAIR_HOME         —— 指向安装根（含 hwdesktop/ 的那一层）
    3. Windows 卸载注册表            —— 读 Altair HyperWorks/HyperMesh 的 InstallLocation
    4. 常见安装目录扫描              —— Program Files / 各盘符下的 Altair* 目录
    5. PATH 里的 hmopengl.exe

多版本并存时（本机就同时有 2021.2 / 2022.3 / 2025）默认取**版本号最高**的一个，
可用 HWMCP_HM_VERSION 锁定（如 ``2021.2``），doctor 会把所有候选列出来。

设计约束
--------
* 只用标准库：``os`` / ``sys`` / ``glob`` / ``re`` / ``pathlib``，注册表用 ``winreg``
  且整体 try/except 包住，非 Windows 平台自动降级为纯目录扫描。
* 任何函数都不在「找不到」时抛异常，而是返回 ``None`` 让调用方给出人话报错。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# hmopengl.exe 相对安装根的路径。GUI 版必须有：批处理模式下 g_profile_name 恒为
# HyperMesh，材料/工况命令会失效，所以交互族只认 hmopengl。
HM_GUI_REL = Path("hwdesktop") / "hm" / "bin" / "win64" / "hmopengl.exe"
# hmbatch.exe 与 GUI 版同目录，批处理族用它。
HM_BATCH_REL = Path("hwdesktop") / "hm" / "bin" / "win64" / "hmbatch.exe"

_VERSION_RE = re.compile(r"Altair[ _-]?(\d{4}(?:\.\d+)?)", re.IGNORECASE)


def _norm(p: str | os.PathLike) -> str:
    return str(Path(p).expanduser().resolve()) if p else ""


def _version_key(text: str) -> tuple:
    """把 '2021.2' / 'Altair2025' 之类转成可排序元组，无法解析的排最后。"""
    m = _VERSION_RE.search(text)
    raw = m.group(1) if m else ""
    if not raw:
        # 退化：抓目录名里第一段数字
        m2 = re.search(r"(\d{4}(?:\.\d+)?)", text)
        raw = m2.group(1) if m2 else ""
    if not raw:
        return (0, 0)
    parts = raw.split(".")
    major = int(parts[0]) if parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return (major, minor)


# --------------------------------------------------------------- 注册表来源
def _registry_homes() -> list[Path]:
    """从 Windows 卸载表里捞 Altair HyperWorks / HyperMesh 的 InstallLocation。"""
    if sys.platform != "win32":
        return []
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return []

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    found: list[Path] = []
    for hive, sub in roots:
        try:
            base = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        with base:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, name) as k:
                        try:
                            display = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        except OSError:
                            continue
                        # 只要真正带 hm/bin 的桌面产品，Help/Solvers/ConnectMe 一律排除
                        low = display.lower()
                        if "altair" not in low:
                            continue
                        if not any(t in low for t in ("hyperworks", "hypermesh", "hwdesktop")):
                            continue
                        if any(t in low for t in ("help", "solver", "connectme", "inspire")):
                            continue
                        try:
                            loc = str(winreg.QueryValueEx(k, "InstallLocation")[0]).strip()
                        except OSError:
                            continue
                        if loc and (Path(loc) / HM_GUI_REL).is_file():
                            p = Path(loc)
                            if p not in found:
                                found.append(p)
                except OSError:
                    continue
    return found


# --------------------------------------------------------------- 目录扫描来源
def _scan_roots() -> list[Path]:
    """扫常见安装根下的 Altair* 目录。只下探一层，不做全盘递归。"""
    bases: list[Path] = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            v = os.environ.get(env)
            if v:
                bases.append(Path(v))
        for drive in "CDEFGH":
            root = Path(f"{drive}:/")
            if not root.exists():
                continue
            bases.append(root)
            for sub in ("Program", "Program Files", "Programs", "Apps", "software", "Software", "Altair"):
                p = root / sub
                if p.is_dir():
                    bases.append(p)
    else:
        bases += [Path("/opt"), Path("/usr/local"), Path.home()]

    found: list[Path] = []
    for base in bases:
        try:
            if not base.is_dir():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                if "altair" not in child.name.lower():
                    continue
                if (child / HM_GUI_REL).is_file() and child not in found:
                    found.append(child)
        except (OSError, PermissionError):
            continue
    return found


# --------------------------------------------------------------- 汇总与选择
def find_installations() -> list[Path]:
    """返回所有可用安装根（去重、按版本从高到低排序）。"""
    seen: dict[str, Path] = {}

    def add(p: Path) -> None:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            return
        if key not in seen and (p / HM_GUI_REL).is_file():
            seen[key] = p

    env_home = os.environ.get("ALTAIR_HOME")
    if env_home:
        add(Path(env_home))

    for p in _registry_homes():
        add(p)
    for p in _scan_roots():
        add(p)

    return sorted(seen.values(), key=lambda p: _version_key(p.name), reverse=True)


def find_hm_exe(version: str | None = None) -> str | None:
    """定位 hmopengl.exe 的绝对路径；找不到返回 None。

    参数
    ----
    version : 形如 ``"2021.2"``，锁定某个安装版本；None 表示取最高版本。
    """
    explicit = os.environ.get("HWMCP_HM_EXE")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return _norm(p)
        # 显式指定但路径不存在：不要静默回退，让 doctor 报出来
        return None

    want = version or os.environ.get("HWMCP_HM_VERSION")
    for home in find_installations():
        if want and want not in home.name:
            continue
        exe = home / HM_GUI_REL
        if exe.is_file():
            return _norm(exe)
    return None


def find_hm_batch(exe: str | None = None) -> str | None:
    """由 hmopengl.exe 推出同目录的 hmbatch.exe；单独找不到时再全局搜一遍。"""
    exe = exe or find_hm_exe()
    if exe:
        sib = Path(exe).with_name("hmbatch.exe")
        if sib.is_file():
            return _norm(sib)
    for home in find_installations():
        b = home / HM_BATCH_REL
        if b.is_file():
            return _norm(b)
    return None


def find_python() -> str:
    """MCP 客户端该用哪个 python 起服务：就是当前解释器。

    原来的写法把某个 conda/pyenv 的绝对路径写死，换机必炸。用 sys.executable
    永远指向「正在跑这段代码的解释器」，天然正确。
    """
    return _norm(sys.executable)


def describe() -> dict:
    """给 doctor / --self-check 用的完整环境画像。"""
    exe = find_hm_exe()
    inst = find_installations()
    return {
        "python": find_python(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "hm_exe": exe,
        "hm_batch": find_hm_batch(exe),
        "installations": [{"root": str(p), "version": ".".join(map(str, _version_key(p.name)))} for p in inst],
        "source": (
            "HWMCP_HM_EXE" if os.environ.get("HWMCP_HM_EXE")
            else "ALTAIR_HOME" if os.environ.get("ALTAIR_HOME")
            else "registry+scan" if inst else "not-found"
        ),
        "hw_config_path": os.environ.get("HW_CONFIG_PATH"),
        "altair_license": os.environ.get("ALTAIR_LICENSE_PATH"),
    }


if __name__ == "__main__":
    import json

    argv = sys.argv[1:]
    # --print <key>：只输出一个值，方便 .bat 用 for /f 读取（避免在批处理里解析 JSON）
    if len(argv) >= 2 and argv[0] == "--print":
        value = describe().get(argv[1])
        print(value if isinstance(value, str) else ("" if value is None else json.dumps(value)))
        raise SystemExit(0 if value else 1)

    print(json.dumps(describe(), indent=2, ensure_ascii=False))
