"""测试夹具：按需生成纯文本 OptiStruct deck。

为什么不用现成 .fem 文件
------------------------
本机装有透明加密客户端（E-SafeNet），HyperMesh 生成的文件在磁盘上是密文，
只有白名单进程能读到明文。把这种文件提交进 Git，别人 clone 下来就是乱码。
所以夹具改为**运行时生成**——纯 Python 拼字符串，任何机器上都是可读明文。

生成的 deck 只用于验证 `hm_deck_report` 这类离线解析工具，
不需要能真求解，因此刻意做得很小（4 GRID + 1 CQUAD4）。
"""

from __future__ import annotations

from pathlib import Path

# 8 字符定宽字段，符合 OptiStruct/Nastran 小字段格式
_F = "{:<8}"


def _card(*fields: object) -> str:
    return "".join(_F.format(f) for f in fields).rstrip()


def build_minimal_deck() -> str:
    lines = [
        "SOL 101",
        "CEND",
        "SUBCASE        1",
        "  LABEL fixture",
        "  SPC =         1",
        "  LOAD =        2",
        "BEGIN BULK",
        _card("GRID", 1, "", 0.0, 0.0, 0.0),
        _card("GRID", 2, "", 10.0, 0.0, 0.0),
        _card("GRID", 3, "", 10.0, 10.0, 0.0),
        _card("GRID", 4, "", 0.0, 10.0, 0.0),
        _card("CQUAD4", 1, 1, 1, 2, 3, 4),
        _card("PSHELL", 1, 1, 2.0),
        _card("MAT1", 1, 210000.0, "", 0.3, "", 7.85e-09),
        _card("SPC", 1, 1, 123456, 0.0),
        _card("SPC", 1, 2, 123456, 0.0),
        _card("FORCE", 2, 3, "", 100.0, 0.0, 0.0, -1.0),
        "ENDDATA",
    ]
    return "\n".join(lines) + "\n"


def looks_corrupt(path: Path) -> bool:
    """识别「不是给人看的文本」：空文件、含 NUL、或被透明加密（E-SafeNet 头）。"""
    try:
        raw = path.read_bytes()[:512]
    except OSError:
        return True
    if not raw.strip():
        return True
    return b"\x00" in raw or b"E-SafeNet" in raw


def ensure_minimal_deck(path: Path) -> Path:
    """缺失或已损坏时重建，返回最终路径。"""
    path = Path(path)
    if path.is_file() and not looks_corrupt(path):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = build_minimal_deck()
    if path.exists():
        path.unlink()  # 覆盖加密文件时先删，避免写入被驱动接管成密文
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fixture_plate.fem")
    print("写入", ensure_minimal_deck(out))
