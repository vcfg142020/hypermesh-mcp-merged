"""逐工具验证合并后的 54 个 HyperMesh MCP 工具。

分四个阶段，跨阶段共享同一进程状态，阶段间重启：

  A 离线      不需要 HyperMesh、不占 license（纯生成器 / 纯规则 / 路径探测）
  B 交互      常驻 GUI 会话，跑完整板壳算例（占 1 个 license，约 40 秒）
  C 实体      交互族里需要实体模型的工具（MidMesh）
  D 批处理    真起 hmbatch 进程（每次占 license 约 20-40 秒）

输出：out/mcp_tools_verification.md + .json

用法：
    python verify_tools.py            # 全跑
    python verify_tools.py --phase A  # 只跑某阶段
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from _mcpclient import MCPClient

ROOT = Path(__file__).resolve().parent
HW = ROOT.parent
OUT = HW / "out"
OUT.mkdir(exist_ok=True)
VERIFY = OUT / "verify"
VERIFY.mkdir(exist_ok=True)

DEMO_DECK = HW / "hwmcp" / "workspace" / "demo_plate.fem"
EXPORT_DECK = VERIFY / "merged_plate.fem"
SAVED_HM = VERIFY / "merged_plate.hm"
EXISTING_HM = HW / "hwmcp" / "workspace" / "e2e_plate.hm"
RECORDED_TCL = VERIFY / "recorded_sample.tcl"

# 合成探针输入：一块 200x200x4 的板 + 一个 R=50/H=120 的圆柱
PROBE_LINES = [
    "MCP_PROBE_SOLID id=1 exists=1 surf_count=6 elem_count=48 bbox_ok=1 "
    "dx=200 dy=200 dz=4 min_dim=4 max_dim=200 mid_dim=200 diagonal=283 "
    "slender=1 drag_axis=x source_surface_id=11 source_loop_count=4 "
    "source_inner_loop_count=0 source_boundary_edge_count=4 source_boundary_node_count=8",
    "MCP_PROBE_SOLID id=2 exists=1 surf_count=3 elem_count=64 bbox_ok=1 "
    "dx=100 dy=100 dz=120 min_dim=100 max_dim=120 mid_dim=100 diagonal=181 "
    "slender=0 drag_axis= gear_axis=z axis_mode=global axis_vec={0 0 1} "
    "axis_p0={0 0 0} axis_p1={0 0 120} source_surface_id=-1 "
    "source_loop_count=0 source_inner_loop_count=0 source_boundary_edge_count=0 "
    "source_boundary_node_count=0",
]

results: list[dict] = []


def record(phase: str, tool: str, status: str, detail: str, elapsed: float = 0.0) -> None:
    results.append({"phase": phase, "tool": tool, "status": status,
                    "detail": detail, "elapsed_s": round(elapsed, 2)})
    mark = {"PASS": "✓", "FAIL": "✗", "N/A": "–", "PARTIAL": "±"}.get(status, "?")
    print(f"  {mark} [{status:7s}] {tool:42s} {detail[:110]}  ({elapsed:.1f}s)")


def check(phase: str, client: MCPClient, tool: str, args: dict,
          want: str = "ok", contains: str | None = None,
          timeout: float = 300, note: str = "") -> object:
    """want: ok / error / reject。

    error  = 传输层报错（isError=true，JSON-RPC 层拒绝）
    reject = 业务层拒绝（isError=false 但 payload.success=false）
    contains 用于额外内容断言。
    """
    payload, is_error, elapsed, text = client.call(tool, args, timeout=timeout)
    if payload is None:
        record(phase, tool, "FAIL", f"无响应：{text[:80]}")
        return None
    blob = text if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    if want == "error":
        if is_error:
            record(phase, tool, "PASS", f"按预期拒绝：{blob[:90]}")
            return payload
        record(phase, tool, "FAIL", f"应当报错却成功：{blob[:90]}")
        return payload

    if want == "reject":
        if isinstance(payload, dict) and payload.get("success") is False:
            reason = str(payload.get("message") or payload.get("error") or "")[:70]
            record(phase, tool, "PASS", (note or "按预期拒绝") + f"：{reason}", elapsed)
            return payload
        record(phase, tool, "FAIL", f"应当在业务层拒绝却成功：{blob[:90]}", elapsed)
        return payload

    if is_error:
        record(phase, tool, "FAIL", f"报错：{blob[:110]}", elapsed)
        return payload

    if isinstance(payload, dict) and payload.get("success") is False:
        record(phase, tool, "PARTIAL", f"返回 success=false：{blob[:100]}", elapsed)
        return payload

    if contains and contains not in blob:
        record(phase, tool, "FAIL", f"缺少预期内容 '{contains}'：{blob[:90]}", elapsed)
        return payload

    record(phase, tool, "PASS", (note or blob[:110]), elapsed)
    return payload


def na(phase: str, tool: str, reason: str) -> None:
    record(phase, tool, "N/A", reason)


def _ids(payload: object) -> list[int]:
    """hm_find_entities 的返回键是 results；with_coords 时元素为 {id,xyz}。"""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("results") or payload.get("ids") or []
    out: list[int] = []
    for it in raw:
        if isinstance(it, dict) and "id" in it:
            out.append(int(it["id"]))
        elif isinstance(it, (int, float)):
            out.append(int(it))
    return out


# ----------------------------------------------------------------- 阶段 A 离线

def phase_a() -> None:
    print("\n=== A 离线阶段（不启动 HyperMesh，不占 license）===")
    c = MCPClient(autostart=False)
    init, dt = c.initialize()
    tools = c.list_tools()
    print(f"  initialize {dt*1000:.0f} ms，tools/list {len(tools)} 个")

    check("A", c, "locate_hypermesh", {}, contains="hmbatch.exe")
    check("A", c, "get_hypermesh_meshing_strategy", {}, contains="strategy")
    check("A", c, "get_meshing_rules", {}, contains="tetra_surface_deviation_rtrias")
    check("A", c, "get_cutsection_spin_workflow", {}, contains="spin")
    check("A", c, "create_gui_listener_tcl", {}, contains="script_path")
    check("A", c, "generate_geometry_probe_tcl", {}, contains="MCP_PROBE_SOLID")

    check("A", c, "classify_all_solids_from_probe", {"probe_lines": PROBE_LINES})
    check("A", c, "suggest_component_names", {"probe_lines": PROBE_LINES})
    check("A", c, "recommend_tetra_sizes_from_probe_lines", {"probe_lines": PROBE_LINES})

    check("A", c, "generate_rename_components_tcl", {}, contains="tcl_script")
    check("A", c, "generate_component_colors_tcl", {}, contains="tcl_script")
    check("A", c, "generate_finalize_components_tcl", {"assignments": [
        {"component_id": 12, "old_name": "component12",
         "new_name": "verify_s12", "strategy": "drag_hex"}]}, contains="MCP_FINALIZE_OK")
    check("A", c, "generate_phase2_finalize_tcl", {})

    check("A", c, "generate_surface_automesh_tcl", {"element_size": 5.0})
    check("A", c, "generate_plain_tetra_tcl",
          {"solid_id": 1, "component_name": "verify_tet", "element_size": 5.0}, timeout=60)
    check("A", c, "generate_batched_plain_tetra_tcl", {"solids": [
        {"solid_id": 1, "component_name": "verify_tet_a", "element_size": 5.0}]}, timeout=60)
    check("A", c, "generate_guarded_drag_hex_tcl",
          {"source_surface_id": 11, "drag_distance": 100.0,
           "element_size": 5.0, "component_name": "verify_drag"}, timeout=60)
    check("A", c, "generate_batched_drag_hex_tcl", {"solids": [
        {"solid_id": 1, "source_surface_id": 11, "drag_distance": 100.0,
         "component_name": "verify_drag_a", "axis": "x"}]}, timeout=60)
    check("A", c, "generate_cutsection_spin_hex_tcl",
          {"solid_id": 2, "component_name": "verify_spin",
           "split_plane_normal": [0, 1, 0], "split_plane_point": [0, 0, 0],
           "spin_axis": "z", "spin_axis_vector": [0, 0, 1],
           "spin_axis_point": [0, 0, 0]}, timeout=60)
    # 运行时必填但未进 inputSchema.required：应给出可读的参数错误而不是崩溃
    check("A", c, "generate_cutsection_spin_hex_tcl",
          {"solid_id": 2, "component_name": "verify_spin",
           "split_plane_normal": [0, 1, 0], "split_plane_point": [0, 0, 0]},
          want="error", note="缺 spin_axis_point 时给出参数错误（inputSchema 缺陷）", timeout=60)
    check("A", c, "generate_gear_tooth_preview_tcl", {}, timeout=60)
    check("A", c, "generate_delete_gear_tooth_preview_tcl", {}, timeout=60)
    check("A", c, "write_gear_tooth_recognition_report", {}, timeout=60)
    check("A", c, "write_chinese_meshing_workflow_report", {"report_data": {
        "model": "verify_plate", "solids": 1, "strategy": "tetra_plain",
        "note": "MCP 合并版工具验证"}}, timeout=60)

    if not RECORDED_TCL.exists():
        RECORDED_TCL.write_text(
            "*createmark nodes 1 \"all\"\nputs \"recorded-sample\"\n", encoding="utf-8")
    check("A", c, "make_recorded_tcl_wrapper",
          {"recorded_tcl_path": str(RECORDED_TCL)}, timeout=60)

    # 负向：白名单必须在起进程之前拦下（不消耗 license）
    check("A", c, "execute_tcl",
          {"script": "proc x {} {}\n*tetmesh 1 0 0 0", "enforce_meshing_rules": True},
          want="reject", note="网格命令白名单生效", timeout=60)
    check("A", c, "get_gui_async_job_status", {"job_id": "not-a-real-job"},
          want="reject", note="不存在的任务被正确拒绝", timeout=30)

    # 交互族中唯一不依赖 HyperMesh 的工具
    check("A", c, "hm_deck_report", {"path": str(DEMO_DECK)}, contains="CQUAD4")

    for tool, why in [
        ("start_hypermesh_gui_listener", "会再拉一个可见 GUI，与常驻会话争 license；需人工交互，未纳入自动验证"),
        ("run_geometry_probe_gui", "依赖可见 GUI listener 被手工 source，自动验证会挂起"),
        ("execute_tcl_gui", "同上：需要先在 GUI 里 source listener Tcl"),
        ("execute_tcl_gui_async", "同上：需要可见 GUI listener"),
        ("automesh_surfaces_gui", "同上：需要可见 GUI listener"),
    ]:
        na("A", tool, why)

    c.close()


# ----------------------------------------------------------------- 阶段 B 交互

def phase_b() -> None:
    print("\n=== B 交互阶段（常驻 GUI 会话，占 1 个 license）===")
    c = MCPClient(autostart=True)
    init, dt = c.initialize()
    print(f"  initialize {dt*1000:.0f} ms（预热在后台线程，握手不受影响）")

    st = check("B", c, "hm_status", {}, contains="OptiStruct", timeout=180,
               note="profile=OptiStruct")
    if st:
        print(f"     port={st.get('port')} exe={Path(str(st.get('exe',''))).name}")

    check("B", c, "hm_new_model", {"component": "verify_plate"}, timeout=120)
    check("B", c, "hm_create_component", {"name": "verify_extra"}, timeout=60)
    check("B", c, "hm_create_plane_surface", {"size": 200.0}, timeout=120)
    mesh = check("B", c, "hm_mesh_surfaces", {"element_size": 10.0}, timeout=180)
    if isinstance(mesh, dict):
        elems = mesh.get("elements", mesh.get("elems"))
        nodes = mesh.get("nodes")
        ok = (elems == 400 and nodes == 441)
        record("B", "hm_mesh_surfaces#accuracy", "PASS" if ok else "FAIL",
               f"期望 400 单元/441 节点，实测 {elems}/{nodes}")

    check("B", c, "hm_create_material",
          {"name": "Steel", "E": 210000, "nu": 0.3, "rho": 7.85e-9}, timeout=60)
    check("B", c, "hm_create_property",
          {"name": "Plate", "thickness": 2.0, "material": "Steel"}, timeout=60)
    check("B", c, "hm_assign_property",
          {"component": "verify_plate", "property": "Plate"}, timeout=60)

    found = check("B", c, "hm_find_entities",
                  {"mode": "box", "min": [-101, -101, -1], "max": [-99, 101, 1]},
                  timeout=60)
    left_nodes = _ids(found)
    record("B", "hm_find_entities#accuracy", "PASS" if len(left_nodes) == 21 else "FAIL",
           f"期望左边界 21 个节点，实测 {len(left_nodes)}")

    check("B", c, "hm_list_entities", {"entity_type": "comps"}, timeout=60)
    check("B", c, "hm_model_summary", {}, timeout=60)

    check("B", c, "hm_create_loadcollector", {"name": "SPC_LC"}, timeout=60)
    if left_nodes:
        check("B", c, "hm_add_constraints",
              {"loadcollector": "SPC_LC", "nodes": left_nodes, "dofs": [1, 2, 3]}, timeout=90)

    center = check("B", c, "hm_find_entities",
                   {"mode": "box", "min": [-6, -6, -1], "max": [6, 6, 1],
                    "with_coords": True}, timeout=60)
    center_ids = _ids(center)[:1]

    check("B", c, "hm_create_loadcollector", {"name": "FORCE_LC"}, timeout=60)
    if center_ids:
        check("B", c, "hm_add_force",
              {"loadcollector": "FORCE_LC", "nodes": center_ids, "fz": -100}, timeout=90)

    check("B", c, "hm_create_loadstep",
          {"name": "static1", "spc_loadcollector": "SPC_LC",
           "load_loadcollector": "FORCE_LC"}, timeout=90)

    exported = check("B", c, "hm_export",
                     {"path": str(EXPORT_DECK), "solver": "optistruct"}, timeout=180)
    if isinstance(exported, dict):
        counts = exported.get("report", {}).get("counts", {}) or exported.get("counts", {})
        want = {"GRID": 441, "CQUAD4": 400, "PSHELL": 1, "MAT1": 1,
                "SPC": 126, "FORCE": 1, "SUBCASE": 1}
        got = {k: counts.get(k) for k in want}
        ok = all(got[k] == v for k, v in want.items())
        record("B", "hm_export#accuracy", "PASS" if ok else "FAIL",
               f"期望 {want}，实测 {got}")
        cc = exported.get("report", {}).get("case_control") or []
        record("B", "hm_export#case_control",
               "PASS" if any("SUBCASE" in str(x) for x in cc) else "FAIL",
               f"case control: {cc}")

    if EXPORT_DECK.exists():
        rep = check("B", c, "hm_deck_report", {"path": str(EXPORT_DECK)}, contains="SUBCASE")
        if isinstance(rep, dict):
            counts = rep.get("counts", {})
            got = {k: counts.get(k) for k in ("GRID", "CQUAD4", "SPC", "FORCE")}
            ok = got.get("CQUAD4") == 400 and got.get("GRID") == 441 and got.get("SPC") == 126
            record("B", "hm_deck_report#accuracy", "PASS" if ok else "FAIL", f"计数 {got}")

    check("B", c, "hm_save_model", {"path": str(SAVED_HM)}, timeout=120)
    check("B", c, "hm_run_tcl", {"script": "expr {2+3}"}, contains="5", timeout=60)
    check("B", c, "hm_open_model", {"path": str(EXISTING_HM)}, timeout=180)

    na("B", "hm_midmesh_extract", "见阶段 C：需要实体模型")
    c.close()


# ----------------------------------------------------------------- 阶段 C 实体

def phase_c() -> None:
    print("\n=== C 实体阶段（MidMesh，需要实体模型）===")
    c = MCPClient(autostart=True)
    c.initialize()

    made = check("C", c, "hm_new_model", {"component": "solid_block"}, timeout=180)
    # *solidblock 真实签名是 12 个参数（原点 + 三个边长向量），且必须已有当前 component
    build = (
        "*currentcollector components solid_block\n"
        "*solidblock -100 -100 0  200 0 0  0 200 0  0 0 4\n"
        "*createmark solids 1 all\n"
        "hm_marklength solids 1"
    )
    got = check("C", c, "hm_run_tcl", {"script": build}, timeout=180,
                note="12 参数 *solidblock 造出 1 个 solid")
    if isinstance(got, dict):
        n = int(str(got.get("result", "0")).strip() or 0)
        record("C", "hm_run_tcl#solidblock", "PASS" if n == 1 else "FAIL",
               f"期望 1 个 solid，实测 {n}")

    ext = check("C", c, "hm_midmesh_extract", {"element_size": 10.0}, timeout=300)
    if isinstance(ext, dict):
        comps = ext.get("components") or ext.get("comps") or []
        # 2D 中面组件名形如 Midmesh.1；^MidmeshEdges.1 是 1D 边界单元，不算在内
        twod = sum(int(x.get("elems", 0)) for x in comps
                   if str(x.get("name", "")).startswith("Midmesh."))
        oned = sum(int(x.get("elems", 0)) for x in comps
                   if "Edges" in str(x.get("name", "")))
        names = [x.get("name") for x in comps]
        ok = twod == 400 and oned == 80
        record("C", "hm_midmesh_extract#accuracy", "PASS" if ok else "FAIL",
               f"期望 400 个 2D + 80 个 1D 边，实测 {twod}/{oned}；组件 {names}")
    c.close()


# ----------------------------------------------------------------- 阶段 D 批处理

def phase_d() -> None:
    print("\n=== D 批处理阶段（真起 hmbatch，每次占 license）===")
    c = MCPClient(autostart=False)
    c.initialize()

    check("D", c, "check_hypermesh_connection", {}, timeout=300)
    check("D", c, "execute_tcl",
          {"script": "puts \"merged-verify-ok\"\nset n 1", "timeout_seconds": 180},
          timeout=300, contains="merged-verify-ok")

    if EXISTING_HM.exists():
        out_hm = VERIFY / "automesh_out.hm"
        out_hm.unlink(missing_ok=True)
        check("D", c, "automesh_surfaces",
              {"input_hm_path": str(EXISTING_HM), "output_hm_path": str(out_hm),
               "element_size": 20.0}, timeout=300)
        record("D", "automesh_surfaces#artifact",
               "PASS" if out_hm.exists() else "FAIL",
               f"输出文件 {'已生成' if out_hm.exists() else '未生成'}")

        # 准确性：200×200 板按 20mm 划分应为 10×10=100 个单元、11×11=121 个节点
        if out_hm.exists():
            probe = (
                "*createmark elems 1 all\n"
                "set ne [hm_marklength elems 1]\n"
                "*createmark nodes 1 all\n"
                "set nn [hm_marklength nodes 1]\n"
                'puts "MCP_COUNT=ELEMS=$ne NODES=$nn"\n'
                "set __mcp_rc 0"
            )
            p, _e, _el, txt = c.call("execute_tcl",
                                     {"script": probe, "model_path": str(out_hm),
                                      "timeout_seconds": 180}, timeout=300)
            so = p.get("stdout", "") if isinstance(p, dict) else str(txt)
            import re as _re
            hit = _re.search(r"MCP_COUNT=ELEMS=(\d+) NODES=(\d+)", so)
            e_n = int(hit.group(1)) if hit else -1
            n_n = int(hit.group(2)) if hit else -1
            record("D", "automesh_surfaces#accuracy",
                   "PASS" if (e_n, n_n) == (100, 121) else "FAIL",
                   f"期望 100 单元/121 节点，实测 {e_n}/{n_n}")
    else:
        na("D", "automesh_surfaces", f"缺少输入模型 {EXISTING_HM}")
    c.close()


def main() -> int:
    phases = {"A": phase_a, "B": phase_b, "C": phase_c, "D": phase_d}
    want = [a.split("=")[1].upper() for a in sys.argv if a.startswith("--phase=")]
    todo = want or ["A", "B", "C", "D"]

    t0 = time.time()
    for key in todo:
        try:
            phases[key]()
        except Exception as exc:  # noqa: BLE001
            record(key, "<phase>", "FAIL", f"阶段异常：{type(exc).__name__}: {exc}")

    # ---- 汇总 ----
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n===== 汇总（{time.time()-t0:.0f}s）=====")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    (OUT / "mcp_tools_verification.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["| # | 阶段 | 工具 | 结果 | 耗时 | 证据 |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        detail = r["detail"].replace("|", "\\|")[:150]
        lines.append(f"| {i} | {r['phase']} | `{r['tool']}` | {r['status']} | "
                     f"{r['elapsed_s']}s | {detail} |")
    (OUT / "mcp_tools_verification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  报告：{OUT / 'mcp_tools_verification.md'}")
    return 0 if counts.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
