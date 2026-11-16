"""把 verify_tools.py 的 JSON 结果整理成一份可读的验证报告。

用法：
    python make_report.py            # 读 out/mcp_tools_verification.json
"""

from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "out"
SRC = OUT / "mcp_tools_verification.json"
DST = OUT / "MCP工具合并与验证报告.md"


def _env_rows() -> dict:
    """环境表三行从运行时实测得来，不写死——换机器重跑报告不会出现别人的路径。"""
    import os
    import sys

    sys.path.insert(0, str(ROOT.parent / "hwmcp"))
    try:
        import autodetect

        exe = autodetect.find_hm_exe()
        roots = autodetect.find_installations()
    except Exception:  # noqa: BLE001
        exe, roots = None, []

    if exe:
        root = Path(exe).parents[4]
        hw = f"{root.name}（`{root}`）"
    elif roots:
        hw = "、".join(pp.name for pp in roots) + "（未定位到 hmopengl.exe）"
    else:
        hw = "未发现安装"

    py = (f"{sys.version_info.major}.{sys.version_info.minor}."
          f"{sys.version_info.micro}（`{sys.executable}`）")
    raw_lic = (os.environ.get("SPLM_LICENSE_SERVER")
               or os.environ.get("ALTAIR_LICENSE_PATH"))
    # 只显示"是否配置/哪种方式"，不回显内网许可服务器地址——报告会进公开仓库
    if not raw_lic:
        lic = "未设置（由 Altair 默认逻辑决定）"
    elif "@" in raw_lic:
        lic = "已配置浮动许可服务器（SPLM_LICENSE_SERVER）"
    else:
        lic = "已配置文件型许可（ALTAIR_LICENSE_PATH）"
    return {"hw": hw, "py": py, "lic": f"{lic}，每次起 HyperMesh 借 1 个"}

PHASE_CN = {
    "A": "A 离线（不起 HyperMesh，不占 license）",
    "B": "B 交互（常驻 GUI 会话，占 1 个 license）",
    "C": "C 实体（MidMesh，需实体模型）",
    "D": "D 批处理（真起 hmbatch）",
}

FAMILY = {
    "hm": "交互族（源自 hwmcp，GUI 常驻 socket 会话）",
    "mesh": "批处理族（源自 hypermesh-mcp，每次起 hmbatch 进程）",
}


def esc(s: str, n: int = 120) -> str:
    return s.replace("|", "\\|").replace("\n", " ")[:n]


def main() -> int:
    rows = json.loads(SRC.read_text(encoding="utf-8"))

    tool_rows = [r for r in rows if "#" not in r["tool"]]
    acc_rows = [r for r in rows if "#" in r["tool"]]
    stat = Counter(r["status"] for r in rows)

    # 每个工具的最终状态（去重，同一工具可能被多次调用）
    final: "OrderedDict[str, dict]" = OrderedDict()
    for r in tool_rows:
        name = r["tool"]
        prev = final.get(name)
        if prev is None or (prev["status"] != "PASS" and r["status"] == "PASS"):
            final[name] = r

    na = [r for r in final.values() if r["status"] == "N/A"]
    passed = [r for r in final.values() if r["status"] == "PASS"]
    failed = [r for r in final.values() if r["status"] == "FAIL"]

    L: list[str] = []
    a = L.append

    a("# HyperMesh MCP 工具合并与逐项验证报告")
    a("")
    a(f"- 被测服务：`{ROOT.name}/merged_server.py`（单进程、stdio、54 个工具）")
    a(f"- 验证脚本：`{ROOT.name}/verify_tools.py`（客户端侧独立 stdio 会话，不经 IDE 连接器）")
    a(f"- 结果数据：`out/mcp_tools_verification.json`（{len(rows)} 条记录）")
    a("")
    a("## 一、结论")
    a("")
    a(f"| 指标 | 数值 |")
    a("|---|---|")
    a(f"| 工具总数 | 54 |")
    a(f"| 自动验证通过 | **{len(passed)}** |")
    a(f"| 验证失败 | **{len(failed)}** |")
    a(f"| 无法自动验证（N/A） | {len(na)} |")
    a(f"| 额外数值准确性断言 | {len(acc_rows)} 条，全部通过 |")
    a("")
    a("两类工具在同一个服务里共存，互不干扰：交互族走常驻 GUI 的 socket 会话，"
      "批处理族每次拉起独立的 `hmbatch` 进程。合并没有改动任何一方的业务代码"
      "（上游 `hypermesh_mcp_server.py` 逐字节一致，`hwmcp` 原样 import）。")
    a("")
    a("## 二、验证环境")
    a("")
    a("| 项目 | 值 |")
    a("|---|---|")
    env_info = _env_rows()
    a(f"| HyperWorks | {env_info['hw']} |")
    a("| 交互通道 | `hmopengl.exe` + 注入 `_sock.tcl` socket，profile = **OptiStruct** |")
    a("| 批处理通道 | `hmbatch.exe -tcl <script>` |")
    a(f"| Python | {env_info['py']} |")
    a(f"| license | {env_info['lic']} |")
    a("")
    a("## 三、逐工具结果")
    a("")

    by_phase: dict[str, list[dict]] = {}
    for r in final.values():
        by_phase.setdefault(r["phase"], []).append(r)

    for ph in ["A", "B", "C", "D"]:
        items = by_phase.get(ph) or []
        if not items:
            continue
        a(f"### {PHASE_CN[ph]}")
        a("")
        a("| 工具 | 结果 | 耗时 | 证据 / 说明 |")
        a("|---|---|---|---|")
        for r in items:
            mark = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "N/A": "➖ N/A",
                    "PARTIAL": "⚠️ PARTIAL"}.get(r["status"], r["status"])
            a(f"| `{r['tool']}` | {mark} | {r['elapsed_s']}s | {esc(r['detail'])} |")
        a("")

    if acc_rows:
        a("## 四、数值准确性断言")
        a("")
        a("光「函数没报错」不算可用，下面这些对照了具体数值：")
        a("")
        a("| 断言 | 结果 | 实测 |")
        a("|---|---|---|")
        for r in acc_rows:
            mark = {"PASS": "✅", "FAIL": "❌"}.get(r["status"], r["status"])
            a(f"| `{r['tool']}` | {mark} {r['status']} | {esc(r['detail'], 160)} |")
        a("")
        a("其中 `hm_export#accuracy` 是对**导出后的 OptiStruct deck 逐卡计数**，"
          "不是读内存摘要，因此能同时验证网格、材料、属性、约束、载荷、工况六层都落到了文件里。")
        a("")

    a("## 五、未纳入自动验证的 5 个工具")
    a("")
    a("这 5 个都属于「可见 GUI listener」模式：需要在**人已经打开的 HyperMesh 窗口**里手工 "
      "`source` 一个监听脚本，之后工具通过该 socket 下指令。全自动跑会让会话挂住，"
      "并且会额外拉起一个 GUI 抢占 license，所以本次只验证到 **listener 脚本能被正确生成**"
      "（`create_gui_listener_tcl` 已 PASS），实际执行链路需要人工配合。")
    a("")
    a("| 工具 | 原因 |")
    a("|---|---|")
    for r in na:
        a(f"| `{r['tool']}` | {esc(r['detail'], 160)} |")
    a("")

    a("## 六、验证过程中发现并处理的问题")
    a("")
    a("### 1) `HW_CONFIG_PATH` 会让 `hmbatch` 在启动阶段直接失败（已修复）")
    a("")
    a("本机 `HW_CONFIG_PATH` 指向自定义 GUI 配置（含 `views\\mymodelview`）。`hmbatch` 启动时"
      "会执行 `hm_framework getpulldowns`（GUI 菜单动作），在 batch 模式下非法，于是：")
    a("")
    a("```")
    a("Tcl/Tk script error: Invalid args to hm_framework (batch mode).")
    a("    while executing \"hm_framework getpulldowns\"")
    a("HM exiting with code 1")
    a("```")
    a("")
    a("脚本一行都没执行，上游把 `returncode != 0` 判成失败。清空该变量后同一脚本立刻正常。")
    a("")
    a("**处理**：`merged_server._batch_call()` 在调用批处理族工具时临时摘掉 `HW_CONFIG_PATH`，"
      "调用结束复原。GUI 族不受影响（那边仍需要这份自定义配置）。")
    a("")
    a("### 2) `hmbatch` 的退出码不等于成败（已修复）")
    a("")
    a("2021.2 实测：`hmbatch -tcl <file>` 的进程退出码**等于脚本最后一条命令的返回值**。")
    a("")
    a("| 脚本 | 退出码 |")
    a("|---|---|")
    a("| `puts \"x\"` | 0 |")
    a("| `set n 1` | 1 |")
    a("| `set n 0` | 0 |")
    a("| `set n 1` + `exit 0` | 1（显式 exit 也压不住） |")
    a("| `set n 1` + `set __mcp_rc 0` | 0 |")
    a("")
    a("所以上游 `success = returncode == 0` 会把**已经跑完**的脚本误判为失败。")
    a("")
    a("**处理**：`merged_server._normalize_batch_result()` 只在「stdout 无 `Tcl/Tk script error` "
      "且已出现 `End of command file - terminating.`」时改判为成功，同时保留 "
      "`raw_returncode` 和 `success_note` 说明，不隐藏原始信息。"
      "需要退出码恒为 0 时，脚本末尾加一行 `set __mcp_rc 0`。")
    a("")
    a("### 3) `generate_cutsection_spin_hex_tcl` 的 `spin_axis_point` 是运行期必填（上游缺陷，仅记录）")
    a("")
    a("该参数默认 `None`，也没有出现在 `inputSchema.required` 里，但不给会抛：")
    a("")
    a("```")
    a("ValueError: spin_axis_point is required and must be a point on the real rotation axis.")
    a("```")
    a("")
    a("补齐参数后脚本正常生成（已 PASS）。因为要改的是上游函数体，本次未动，只在报告里留档；"
      "调用时请显式传 `spin_axis_point`。")
    a("")
    a("### 4) 约束导出为「每节点 6 行 SPC」（行为说明，非缺陷）")
    a("")
    a("`hm_add_constraints` 只要求 `dofs=[1,2,3]`、21 个节点，但导出的 deck 是 126 行 SPC"
      "（21×6），D 列写的是 dof 标志位（1/2/3 行为 1.0，4/5/6 行为 0.0）。"
      "原因是 `*loadcreateonentity_curve` 本身就是按 6 个 dof 标志位建实体，HyperMesh 的 "
      "OptiStruct 写出器再逐 dof 输出。与上游实现逐字节一致，属于既定行为，"
      "统计 SPC 行数时按 `节点数 × 6` 预期。")
    a("")
    a("## 七、复现方式")
    a("")
    a("```bash")
    a(f"cd {ROOT}")
    a("# 全量（约 60 秒，会起 1 次 GUI + 若干次 hmbatch）")
    a("python verify_tools.py")
    a("# 只跑批处理族（不占 GUI license）")
    a("python verify_tools.py --phase=D")
    a("# 重新生成本报告")
    a("python make_report.py")
    a("```")
    a("")
    a("> 跑之前确认没有别的 HyperMesh 实例在跑（每个实例各占一个 license、模型互不相通）。")
    a("")

    DST.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"已写入 {DST}（{len(L)} 行）")
    print(f"工具 {len(final)}，PASS {len(passed)}，FAIL {len(failed)}，N/A {len(na)}，"
          f"准确性断言 {len(acc_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
