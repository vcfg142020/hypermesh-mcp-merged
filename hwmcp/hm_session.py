"""HyperMesh 会话管理。

设计要点
--------
* 用 **GUI 版** ``hmopengl.exe`` 而不是 ``hmbatch.exe``：批处理模式下求解器
  profile 不会加载（``g_profile_name`` 恒为 ``HyperMesh``），卡片定义缺失，
  ``*setvalue mats ... E`` 之类全部失效；GUI 模式才是完整的 OptiStruct 环境。
* ``-tcl ../_sock.tcl`` 在启动时注入常驻服务，由 HyperMesh 进程自己监听一个
  TCP 端口。这样模型状态可以跨调用保持（前处理是有状态的）。
* 协议：每行一条 Tcl 命令，回 ``OK: <结果>`` 或 ``ERR: <错误>``，结果中的
  换行已被转义成 ``\\n``。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import autodetect

HERE = Path(__file__).resolve().parent
SOCK_TCL = HERE / "_sock.tcl"

# 不再写死安装路径。优先级：显式传参 > HWMCP_HM_EXE > 自动发现（注册表/常见目录）。
# 自动发现见 autodetect.py；找不到时 DEFAULT_EXE 为 None，由 start() 给出人话报错。
DEFAULT_EXE = autodetect.find_hm_exe()

# 导出模板：求解器名 -> feoutput 模板路径片段
TEMPLATES = {
    "optistruct": "optistruct/optistruct",
    "nastran": "nastran/nastran",
    "abaqus": "abaqus/standard.3d",
    "radioss": "radioss/radioss2017.blk",
    "lsdyna": "lsdyna/dyna.key",
}


class HMError(RuntimeError):
    """Tcl 侧返回 ERR 或进程/连接异常。"""


def to_single_line(script: str) -> str:
    """把多行 Tcl 压成单行——协议是按行传输的。

    跳过空行与整行注释，处理行尾续行符，用 ``;`` 连接。
    """
    parts: list[str] = []
    buf: list[str] = []
    for raw in script.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf.append(s[:-1].strip())
            continue
        if buf:
            buf.append(s)
            parts.append(" ".join(buf))
            buf = []
        else:
            parts.append(s)
    if buf:
        parts.append(" ".join(buf))
    return "; ".join(parts)


def tcl_str(value: str) -> str:
    """转成安全的 Tcl 字面量（优先花括号，含特殊字符时退化为转义双引号）。"""
    text = str(value).replace("\\", "/")
    if "{" not in text and "}" not in text and "\\" not in text:
        return "{" + text + "}"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("[", "\\[") + '"'


class HMSession:
    def __init__(self, exe: str | None = None, workdir: str | None = None):
        self.exe = exe or autodetect.find_hm_exe()
        self.workdir = Path(workdir or os.environ.get("HWMCP_WORKDIR") or (HERE / "workspace"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._file = None
        self.model_path: str | None = None
        self._start_lock = threading.Lock()
        # 必须用 RLock：启动流程在持有 io 锁时会再调 self.call()，同线程重入
        self._io_lock = threading.RLock()
        self._hm_log = None
        # 连接代数：每次成功建立新 socket（新 HM 进程 / 重启后的新 Tcl 解释器）自增。
        # 调用方（如 tools._ensure）据此判断注入过的 Tcl 辅助过程是否还在——
        # HM 重启后进程内所有 proc 都会丢失，只靠一个布尔标记会误判成"已注入"。
        self._gen = 0

    # ------------------------------------------------------------------ 进程
    def _pick_port(self) -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout: float = 180.0) -> None:
        """拉起 HyperMesh 并等待常驻服务就绪。可被多个线程并发调用（内部串行化）。"""
        with self._start_lock:
            self._start_locked(timeout)

    def _start_locked(self, timeout: float) -> None:
        # 已就绪（进程活着且 socket 已连）就直接返回；启动进行中则等锁释放后再判断
        if self.is_alive() and self._file is not None:
            return
        if not self.exe:
            raise HMError(
                "找不到 HyperMesh 可执行文件（hmopengl.exe）。已尝试：环境变量 HWMCP_HM_EXE、"
                "ALTAIR_HOME、Windows 卸载注册表、常见安装目录。\n"
                "处置：设置 HWMCP_HM_EXE 指向 hwdesktop/hm/bin/win64/hmopengl.exe，"
                "或设置 HWMCP_HM_VERSION=2021.2 指定版本，或运行 python doctor.py 查看候选。"
            )
        if not Path(self.exe).exists():
            raise HMError(f"HyperMesh 可执行文件不存在：{self.exe}（检查 HWMCP_HM_EXE 是否写错）")
        if not SOCK_TCL.exists():
            raise HMError(f"缺少常驻服务脚本：{SOCK_TCL}")
        if "hmbatch" in Path(self.exe).name.lower():
            # 踩过的坑：hmbatch 下 g_profile_name 恒为 HyperMesh，材料/工况命令全失效。
            print("[hwmcp] 警告：HWMCP_HM_EXE 指向 hmbatch.exe，交互族会失去 OptiStruct profile",
                  file=sys.stderr, flush=True)

        self.port = self._pick_port()
        env = dict(os.environ)
        env["HWMCP_PORT"] = str(self.port)
        # 不要用 DEVNULL：HyperMesh 以 -tcl 启动时会往 stdout 打提示，
        # 在没有控制台的进程里 stdout 可能不存在，导致脚本提前中断。
        # 重定向到文件既能保证通道有效，也留下排查线索。
        self._hm_log = open(HERE / "_hm_session.log", "a", encoding="utf-8", errors="replace")
        self._hm_log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动，端口 {self.port} =====\n")
        self._hm_log.flush()
        self.proc = subprocess.Popen(
            [self.exe, "-tcl", str(SOCK_TCL)],
            cwd=str(HERE),
            env=env,
            stdout=self._hm_log,
            stderr=self._hm_log,
            stdin=subprocess.DEVNULL,
        )
        deadline = time.time() + timeout
        last_err: Exception | None = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise HMError(f"HyperMesh 进程启动后立即退出（返回码 {self.proc.returncode}）")
            try:
                self._connect()
                self.call("set __hwmcp_ok 1", timeout=20)
                return
            except Exception as exc:  # noqa: BLE001 - 启动期任何异常都应重试
                last_err = exc
                self._close()
                time.sleep(2.0)
        raise HMError(f"HyperMesh 在 {timeout:.0f}s 内未就绪：{last_err}")

    def _connect(self) -> None:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=15)
        sock.settimeout(None)
        self._sock = sock
        self._file = sock.makefile("rw", encoding="utf-8", newline="\n")
        self._gen += 1

    def _close(self) -> None:
        try:
            if self._file:
                self._file.close()
        except OSError:
            pass
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._file = None
        self._sock = None

    def stop(self, wait: float = 8.0) -> None:
        # 先停进程再关日志，避免子进程句柄已失效导致写日志报错
        if self.is_alive():
            try:
                self.call("__EXIT__", timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self._close()
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=wait)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.proc = None
        if self._hm_log is not None:
            try:
                self._hm_log.close()
            except Exception:  # noqa: BLE001
                pass
            self._hm_log = None

    def restart(self) -> None:
        self.stop()
        self.start()

    # ------------------------------------------------------------------ 调用
    def call(self, tcl: str, timeout: float = 300.0) -> str:
        ok, text = self._call_raw(to_single_line(tcl), timeout)
        if not ok:
            raise HMError(text)
        return text

    def try_call(self, tcl: str, timeout: float = 300.0) -> tuple[bool, str]:
        return self._call_raw(to_single_line(tcl), timeout)

    def _call_raw(self, line: str, timeout: float) -> tuple[bool, str]:
        # 启动要在拿 IO 锁之前完成：否则预热线程持 _start_lock 等 _io_lock、
        # 调用线程持 _io_lock 等 _start_lock，会死锁。
        if not self.is_alive() or self._file is None:
            self.start()
        # 串行化「写一行 + 读一行」，保证一问一答不串包
        with self._io_lock:
            return self._call_raw_locked(line, timeout)

    def _call_raw_locked(self, line: str, timeout: float) -> tuple[bool, str]:
        if self._file is None:
            self._connect()
        assert self._sock is not None and self._file is not None
        self._sock.settimeout(timeout)
        try:
            self._file.write(line.replace("\n", " ") + "\n")
            self._file.flush()
            reply = self._file.readline()
        except (OSError, socket.timeout) as exc:
            self._close()
            raise HMError(f"与 HyperMesh 通信失败：{exc}") from exc
        if reply == "":
            self._close()
            raise HMError("HyperMesh 关闭了连接（进程可能已崩溃）")
        reply = reply.rstrip("\n")
        text = reply.replace("\\n", "\n")
        if text.startswith("OK:"):
            return True, text[3:].strip()
        if text.startswith("ERR:"):
            return False, text[4:].strip()
        return True, text
