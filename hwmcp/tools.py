"""MCP 工具集：把前处理动作翻译成 HyperMesh Tcl。

所有命令签名均在本机 HyperWorks 2021.2（OptiStruct profile）实测通过：
  * 材料卡片      *createentity mats name=X cardimage=MAT1 + *setvalue mats id=1 E=..
  * 属性卡片      *createentity props name=X cardimage=PSHELL + *setvalue props id=1 95=<T>
  * 材料关联      *setvalue props id=<pid> materialid={mats <mid>}
  * 属性赋予      *setvalue comps id=<cid> propertyid={props <pid>}
  * 2D 网格       *defaultmeshsurf 1 <size> <etype> 0 2 0 0 1 1 0 0 0 0
  * 约束/载荷     *loadcreateonentity_curve nodes <mark> <config> 1 ...
                  config 1 = FORCE，config 2 = MOMENT，config 3 = SPC
  * 工况          *loadstepscreate + *attributeupdate{int,entity} 4143..4147
  * 导出          *feoutputwithdata <template> <file> 0 0 1 1 0
"""

from __future__ import annotations

import re
from pathlib import Path

from hm_session import HMError, HMSession, TEMPLATES, tcl_str

# --------------------------------------------------------------------- 辅助

_BOOTSTRAP = r"""
proc __hwmcp_count {etype} {
    if {[catch {*createmark $etype 1 all} e]} { return -1 }
    return [hm_marklength $etype 1]
}
"""

# 收集器类实体统一用 hm_getvalue name=... 探测（hm_allentitiesinfo 不支持 loadcols）
_ID_PROBE = "catch {{hm_getvalue {etype} name={name} dataname=name}} v; set v"
_ID_GET = "catch {{hm_getvalue {etype} name={name} dataname=id}} v; set v"


def _num(value) -> str:
    """数值转 Tcl 字面量，浮点去掉多余尾零。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    f = float(value)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return f"{f:.12g}"


def _mark_nodes(nodes) -> str:
    if nodes in (None, "all", []):
        return "*createmark nodes 1 all"
    ids = [int(n) for n in nodes]
    if not ids:
        return "*createmark nodes 1 all"
    return '*createmark nodes 1 "by id" ' + " ".join(str(i) for i in ids)


def _ensure(session: HMSession) -> None:
    """按连接代数量一次性定义 Tcl 辅助过程。

    HyperMesh 重启后新进程里没有这些 proc，而 ``HMSession`` 对象是复用的，
    所以不能只记一个布尔标记——必须绑定 ``session._gen``（每次新建 socket 自增）。
    """
    gen = getattr(session, "_gen", 0)
    if getattr(session, "_bootstrap_gen", None) == gen:
        return
    session.call(_BOOTSTRAP, timeout=30)
    session._bootstrap_gen = gen  # type: ignore[attr-defined]


def _id_by_name(session: HMSession, etype: str, name: str):
    """按名称查实体 id；不存在返回 None。

    注意：``hm_getvalue <type> name=X dataname=id`` 对不存在的名字也会返回 1，
    所以先用 ``dataname=name`` 回读校验，确认实体确实存在。
    """
    _ensure(session)
    back = session.call(_ID_PROBE.format(etype=etype, name=tcl_str(name)))
    if back.strip().strip("{}") != name:
        return None
    raw = session.call(_ID_GET.format(etype=etype, name=tcl_str(name)))
    raw = raw.strip().strip("{}")
    try:
        ident = int(raw)
    except ValueError:
        return None
    return ident if ident > 0 else None


def _resolve(session: HMSession, etype: str, name: str) -> int:
    ident = _id_by_name(session, etype, name)
    if ident is None:
        raise HMError(f"找不到 {etype} «{name}»")
    return ident


# --------------------------------------------------------------------- 工具实现


def t_status(s: HMSession, a: dict) -> dict:
    _ensure(s)
    out = s.call(
        "set o {}; "
        "lappend o \"profile=[set g_profile_name]\"; "
        "foreach t {comps mats props loadcols loadsteps elems nodes surfaces solids} "
        "{ lappend o \"$t=[__hwmcp_count $t]\" }; "
        "join $o \";\""
    )
    data = {}
    for item in out.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            data[k.strip()] = v.strip()
    return {
        "running": s.is_alive(),
        "port": s.port,
        "exe": s.exe,
        "profile": data.get("profile"),
        "entities": {k: int(v) for k, v in data.items() if k != "profile" and v.lstrip("-").isdigit()},
    }


def t_new_model(s: HMSession, a: dict) -> dict:
    _ensure(s)
    comp = a.get("component") or "unsorted"
    s.call(f"hm_answernext yes; *deletemodel; *collectorcreateonly components {tcl_str(comp)} \"\" 7")
    return {"ok": True, "component": comp, "message": "模型已清空并建立默认 component"}


def t_open_model(s: HMSession, a: dict) -> dict:
    path = Path(a["path"]).expanduser().resolve()
    if not path.exists():
        raise HMError(f"文件不存在：{path}")
    _ensure(s)
    s.call(f"hm_answernext yes; *readfile {tcl_str(path)}")
    s.model_path = str(path)
    return {"ok": True, "path": str(path), "summary": t_status(s, {})["entities"]}


def t_save_model(s: HMSession, a: dict) -> dict:
    path = Path(a.get("path") or (s.workdir / "model.hm")).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    _ensure(s)
    s.call(f"*writefile {tcl_str(path)} 0")
    s.model_path = str(path)
    return {"ok": True, "path": str(path), "size": path.stat().st_size if path.exists() else None}


def t_summary(s: HMSession, a: dict) -> dict:
    return t_status(s, a)["entities"]


def t_create_component(s: HMSession, a: dict) -> dict:
    _ensure(s)
    name = a["name"]
    if _resolve_soft(s, "comps", name) is None:
        s.call(f"*collectorcreateonly components {tcl_str(name)} \"\" 7")
    cid = _resolve(s, "comps", name)
    return {"ok": True, "component": name, "id": cid}


def _resolve_soft(s: HMSession, etype: str, name: str):
    return _id_by_name(s, etype, name)


def t_create_plane(s: HMSession, a: dict) -> dict:
    _ensure(s)
    size = a.get("size", 100.0)
    n = a.get("normal") or [0, 0, 1]
    nx, ny, nz = (float(n[0]), float(n[1]), float(n[2]))
    s.call(
        f"*surfacemode 4; *createplane 1 {_num(nx)} {_num(ny)} {_num(nz)} 0.0 0.0 0.0; "
        f"*surfaceplane 1 {_num(size)}"
    )
    n_surf = s.call("*createmark surfaces 1 all; hm_marklength surfaces 1")
    return {"ok": True, "surfaces": int(n_surf), "size": size}


def t_mesh(s: HMSession, a: dict) -> dict:
    """曲面 2D 自动网格，按指定单元尺寸一次成形。

    **不要用** ``*interactiveremeshsurf`` + ``*set_meshfaceparams`` + ``*automesh`` 那套面板流程：
    实测其尺寸参数会被面板状态吞掉（传 10 仍得到 2mm），且大尺寸会让 ``*automesh`` 挂起。
    正确入口是 ``*defaultmeshsurf``，签名见 ``hm/scripts/HyperXtrude/layered_ew_g3m.tcl`` 第 204 行注释：

        *defaultmeshsurf markmask elementsize elem_type elem_type2 forcing
                        elemstosurfcomp size_control skew_control edge_mesh_type
                        min_size max_size chordal_div max_angle

    200×200 板实测：尺寸 20/10/5/2 → 100/400/1600/10000 个四边形，尺寸精确。
    该命令自带落库，不需要 ``*storemeshtodatabase``。
    """
    _ensure(s)
    size = a.get("element_size", 10.0)
    etype = int(a.get("element_type", 2))  # 2 = 四边形为主，1 = 三角形
    before = int(s.call("*createmark elems 1 all; hm_marklength elems 1") or 0)
    s.call(
        '*createmark surfaces 1 "displayed"; '
        'if {[hm_marklength surfaces 1] == 0} { return -code error "没有可划分的曲面" }; '
        f"*defaultmeshsurf 1 {_num(size)} {etype} 0 2 0 0 1 1 0 0 0 0",
        timeout=900,
    )
    elems = int(s.call("*createmark elems 1 all; hm_marklength elems 1") or 0)
    nodes = int(s.call("*createmark nodes 1 all; hm_marklength nodes 1") or 0)
    return {
        "ok": True,
        "elements": elems,
        "nodes": nodes,
        "new_elements": elems - before,
        "element_size": size,
    }


def t_create_material(s: HMSession, a: dict) -> dict:
    _ensure(s)
    name = a.get("name", "Steel")
    E = a.get("E", 210000.0)
    nu = a.get("nu", 0.3)
    rho = a.get("rho", 7.85e-09)
    mid = _resolve_soft(s, "mats", name)
    if mid is None:
        s.call(f"*createentity mats name={tcl_str(name)} cardimage=MAT1")
        mid = _resolve(s, "mats", name)
    s.call(
        f"*setvalue mats id={mid} E={_num(E)}; "
        f"*setvalue mats id={mid} Nu={_num(nu)}; "
        f"*setvalue mats id={mid} Rho={_num(rho)}"
    )
    back = s.call(
        f"set o {{}}; foreach k {{E Nu Rho}} "
        f"{{ lappend o \"$k=[hm_getvalue mats id={mid} dataname=$k]\" }}; join $o \", \""
    )
    return {"ok": True, "material": name, "id": mid, "card": "MAT1", "values": back}


def t_create_property(s: HMSession, a: dict) -> dict:
    _ensure(s)
    name = a.get("name", "Plate")
    thick = a.get("thickness", 1.0)
    mat = a.get("material")
    pid = _resolve_soft(s, "props", name)
    if pid is None:
        s.call(f"*createentity props name={tcl_str(name)} cardimage=PSHELL")
        pid = _resolve(s, "props", name)
    tid = s.call("catch {hm_attributeidfromname PSHELL_T props} v; set v")
    tid = tid if tid.isdigit() else "95"
    s.call(f"*setvalue props id={pid} {tid}={_num(thick)}")
    mid = None
    if mat:
        mid = _resolve(s, "mats", mat)
        s.call(f"*setvalue props id={pid} materialid={{mats {mid}}}")
    return {
        "ok": True,
        "property": name,
        "id": pid,
        "card": "PSHELL",
        "thickness": thick,
        "material": mat,
        "material_id": mid,
    }


def t_assign_property(s: HMSession, a: dict) -> dict:
    _ensure(s)
    cid = _resolve(s, "comps", a["component"])
    pid = _resolve(s, "props", a["property"])
    s.call(f"*setvalue comps id={cid} propertyid={{props {pid}}}")
    back = s.call(f"hm_getvalue comps id={cid} dataname=propertyid")
    return {"ok": True, "component": a["component"], "property": a["property"], "propertyid": back}


def t_create_loadcollector(s: HMSession, a: dict) -> dict:
    _ensure(s)
    name = a["name"]
    lid = _resolve_soft(s, "loadcols", name)
    if lid is None:
        s.call(f"*collectorcreate loadcols {tcl_str(name)} \"\" 1")
        lid = _resolve(s, "loadcols", name)
    if a.get("make_current", True):
        s.call(f"*currentcollector loadcols {tcl_str(name)}")
    return {"ok": True, "loadcollector": name, "id": lid}


def _loads(s: HMSession, a: dict, config: int, values: list) -> dict:
    _ensure(s)
    col = a.get("loadcollector", "Loads")
    nodes = a.get("nodes", "all")
    s.call(f"*currentcollector loadcols {tcl_str(col)}")
    before = int(s.call("*createmark loads 1 all; hm_marklength loads 1") or 0)
    vals = " ".join(_num(v) for v in values)
    s.call(f"{_mark_nodes(nodes)}; *loadcreateonentity_curve nodes 1 {config} 1 {vals} 0 0 0 0 0")
    after = int(s.call("*createmark loads 1 all; hm_marklength loads 1") or 0)
    return {"ok": True, "loadcollector": col, "created": after - before, "total_loads": after}


def t_constraints(s: HMSession, a: dict) -> dict:
    dofs = a.get("dofs") or [1, 2, 3]
    flags = [1 if d in dofs else 0 for d in range(1, 7)]
    res = _loads(s, a, 3, flags + [0, 0, 0, 0, 0])
    res["card"] = "SPC"
    res["dofs"] = sorted(dofs)
    return res


def t_force(s: HMSession, a: dict) -> dict:
    vec = [
        a.get("fx", 0.0),
        a.get("fy", 0.0),
        a.get("fz", 0.0),
        a.get("mx", 0.0),
        a.get("my", 0.0),
        a.get("mz", 0.0),
    ]
    res = _loads(s, a, 1, vec + [0, 0, 0, 0, 0])
    res["card"] = "FORCE"
    res["vector"] = vec
    return res


def t_loadstep(s: HMSession, a: dict) -> dict:
    """建工况并把 SPC/LOAD 载荷集绑到 SUBCASE。

    ``*loadstepscreate`` 本身只建一个空工况，真正决定 case control 的是一组
    属性（与 HM 自带 loadstep browser 同源）：
      4143 工况启用、4144/4145 SPC 开关与载荷集、4146/4147 LOAD 开关与载荷集。
    缺 4143 时导出的 deck 只有 SUBCASE/LABEL，没有 ``SPC =`` / ``LOAD =``。
    """
    _ensure(s)
    name = a.get("name", "static1")
    spc_col = a.get("spc_loadcollector")
    load_col = a.get("load_loadcollector")
    if not spc_col and not load_col:
        raise HMError("至少需要指定 spc_loadcollector 或 load_loadcollector")

    lsid = _id_by_name(s, "loadsteps", name)
    created = False
    if lsid is None:
        s.call(f"*loadstepscreate {tcl_str(name)} 1")
        lsid = _id_by_name(s, "loadsteps", name)
        if lsid is None:
            raise HMError("工况创建失败")
        created = True

    script = [
        f"*initializeattributes loadsteps {tcl_str(name)}",
        f"*attributeupdateint loadsteps {lsid} 3239 1 0 0 0",
        f"*attributeupdateint loadsteps {lsid} 3240 1 0 0 3",
        f"*attributeupdateint loadsteps {lsid} 4143 1 0 1 1",
    ]
    bound = {}
    if spc_col:
        sid = _resolve(s, "loadcols", spc_col)
        script += [
            f"*attributeupdateint loadsteps {lsid} 4144 1 0 1 1",
            f"*attributeupdateentity loadsteps {lsid} 4145 1 0 1 loadcols {sid}",
        ]
        bound["spc"] = {"loadcollector": spc_col, "id": sid}
    if load_col:
        lid = _resolve(s, "loadcols", load_col)
        script += [
            f"*attributeupdateint loadsteps {lsid} 4146 1 0 1 1",
            f"*attributeupdateentity loadsteps {lsid} 4147 1 0 1 loadcols {lid}",
        ]
        bound["load"] = {"loadcollector": load_col, "id": lid}

    s.call("\n".join(script))
    total = int(s.call("*createmark loadsteps 1 all; hm_marklength loadsteps 1") or 0)
    return {
        "ok": True,
        "loadstep": name,
        "id": lsid,
        "created": created,
        "bound": bound,
        "total_loadsteps": total,
    }


def t_export(s: HMSession, a: dict) -> dict:
    solver = (a.get("solver") or "optistruct").lower()
    if solver not in TEMPLATES:
        raise HMError(f"不支持的求解器：{solver}（可选：{', '.join(TEMPLATES)}）")
    root = Path(s.exe).parents[4]
    tpl = root / "hwdesktop" / "templates" / "feoutput" / TEMPLATES[solver]
    if not tpl.exists():
        raise HMError(f"找不到导出模板：{tpl}")
    out = Path(a.get("path") or (s.workdir / f"model.{solver[:3]}")).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    _ensure(s)
    s.call(f"hm_answernext yes; *feoutputwithdata {tcl_str(tpl)} {tcl_str(out)} 0 0 1 1 0", timeout=600)
    if not out.exists():
        raise HMError("导出命令返回成功但文件未生成，请检查模板与目标路径")
    return {"ok": True, "path": str(out), "bytes": out.stat().st_size, "solver": solver, "report": deck_report(out)}


# --------------------------------------------------------------------- deck 体检

_CARD = re.compile(r"^\s*([A-Z][A-Z0-9]{1,7})\b")
_WATCH = (
    "GRID CTRIA3 CQUAD4 CTETRA CHEXA CPENTA PSOLID PSHELL MAT1 SPC SPC1 FORCE MOMENT "
    "SUBCASE PLOAD4 RBE2 RBE3 CBUSH PBAR"
).split()


def deck_report(path: Path) -> dict:
    """体检导出的求解器 deck。

    只统计 **bulk data 段**（``BEGIN_BULK`` 之后、``ENDDATA`` 之前）的卡片行。
    早前版本对整个文件做正则，把 case control 里的 ``SPC = 1`` 也当成 SPC 卡片，
    于是 21 个节点 × 6 自由度 = 126 行会报成 127，且 SUBCASE 被重复计入。
    """
    text = path.read_text(errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    counts: dict[str, int] = {}
    case_control: list[str] = []
    spc_nodes: set[int] = set()
    spc_fixed = 0
    in_bulk = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        head = stripped.upper()
        if not in_bulk:
            if head.startswith("BEGIN"):
                in_bulk = True
                continue
            # case control 段：SPC = 1 / LOAD = 2 这类引用不是卡片
            if re.match(r"^(SUBCASE|LABEL|LOAD\s*=|SPC\s*=|MPC\s*=|METHOD\s*=|ANALYSIS\s*=)", stripped):
                case_control.append(stripped)
            continue
        if head.startswith("ENDDATA"):
            in_bulk = False
            continue
        if head.startswith("$"):
            continue
        m = _CARD.match(line)
        if m and m.group(1) in _WATCH:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        if head.startswith("SPC"):
            tok = stripped.split()
            if len(tok) >= 5:
                try:
                    nid, val = int(tok[2]), float(tok[4])
                except ValueError:
                    continue
                spc_nodes.add(nid)
                if val != 0.0:
                    spc_fixed += 1
    n_sub = sum(1 for t in case_control if t.upper().startswith("SUBCASE"))
    if n_sub:
        counts["SUBCASE"] = n_sub
    report = {
        "counts": {k: counts[k] for k in _WATCH if k in counts},
        "case_control": case_control[:40],
        "lines": len(lines),
    }
    if spc_nodes:
        report["spc_detail"] = {"nodes": len(spc_nodes), "fixed_dofs": spc_fixed}
    return report


def t_deck_report(s: HMSession, a: dict) -> dict:
    path = Path(a["path"]).expanduser().resolve()
    if not path.exists():
        raise HMError(f"文件不存在：{path}")
    return {"ok": True, "path": str(path), **deck_report(path)}


def t_find_entities(s: HMSession, a: dict) -> dict:
    """按空间位置标记实体，返回 id 列表。

    实测语义（本机 OptiStruct profile，200×200 板 10mm 网格验证，共 441 节点）：

    * ``box``    —— **体积**选区。参数要凑满 11 个：6 个坐标 + 坐标系 id +
      inside/outside + 3 个标志位。只给 6 个坐标时命令返回 1 但标记为空，
      这是最容易踩的坑。出处：``hm/scripts/meshrefinement.tcl``、``macroBoxTrim.tcl``。
      验证：x=0~100 象限得 2601 个（51×51）；x=-100 那条边界得 21 个。
    * ``sphere`` —— **球面壳**上的实体，不是球体内部。r=10 时得 4 个
      （正好是 (±10,0)(0,±10)），r=15 时得 0（该半径上无格点）。

    ``plane`` 模式**不可用**：``*createmark nodes 1 "by plane" ...`` 无论传 5/6/7 个参数、
    容差 0.1 还是 20，都返回全部 441 个节点——它的平面靠交互拾取定义，不吃数值参数。
    需要平面选区时请用 box 传一个薄盒（厚度方向给 ±容差）。

    单元/曲面同样支持 box（``*createmark elems 1 "by box" ...``）。
    """
    _ensure(s)
    etype = (a.get("entity_type") or "nodes").lower()
    mode = (a.get("mode") or "box").lower()
    inside = "inside" if a.get("inside", True) else "outside"
    limit = int(a.get("limit") or 200)
    with_coords = bool(a.get("with_coords")) and etype == "nodes"

    if mode == "box":
        lo = a.get("min")
        hi = a.get("max")
        if not lo or not hi or len(lo) != 3 or len(hi) != 3:
            raise HMError("box 模式需要 min 与 max，各 3 个数值：[x,y,z]")
        lo_in, hi_in = [float(v) for v in lo], [float(v) for v in hi]
        lo = [min(lo_in[i], hi_in[i]) for i in range(3)]
        hi = [max(lo_in[i], hi_in[i]) for i in range(3)]
        args = " ".join(_num(v) for v in lo + hi)
        mark = f'*createmark {etype} 1 "by box" {args} 0 {inside} 0 0 0'
    elif mode == "sphere":
        c = a.get("center") or [0, 0, 0]
        r = a.get("radius")
        if r is None or len(c) != 3:
            raise HMError("sphere 模式需要 center[x,y,z] 与 radius")
        args = " ".join(_num(v) for v in list(c))
        mark = f'*createmark {etype} 1 "by sphere" {args} {_num(r)} 0 {inside} 0 0 0'
    else:
        raise HMError(f"不支持的 mode：{mode}（可选 box / sphere）")

    total = int(s.call(f"{mark}; hm_marklength {etype} 1") or 0)
    if total == 0:
        return {"ok": True, "entity_type": etype, "mode": mode, "count": 0, "total": 0, "ids": []}

    expr = "[lrange [hm_getmark " + etype + " 1] 0 " + str(limit - 1) + "]"
    body = f"set o {{}}; foreach i {expr} {{ lappend o $i }}; join $o \",\""
    if with_coords:
        body = (
            f"set o {{}}; foreach i {expr} {{ "
            f'lappend o "$i:[hm_getvalue nodes id=$i dataname=x]:'
            f'[hm_getvalue nodes id=$i dataname=y]:[hm_getvalue nodes id=$i dataname=z]" }}; '
            f'join $o ","'
        )
    raw = s.call(body)
    items = [x for x in raw.split(",") if x]
    if with_coords:
        out = []
        for it in items:
            eid, xyz = it.split(":", 1)
            x, y, z = (float(v) for v in xyz.split(":"))
            out.append({"id": int(eid), "xyz": [x, y, z]})
    else:
        out = [int(x) for x in items]

    s.try_call(f"*clearmark {etype} 1")
    return {
        "ok": True,
        "entity_type": etype,
        "mode": mode,
        "inside": inside == "inside",
        "count": len(out),
        "total": total,
        "truncated": total > len(out),
        "results": out,
    }


def t_list_entities(s: HMSession, a: dict) -> dict:
    """枚举实体 id 与名称。

    用 ``*createmark <type> 1 all`` + ``hm_getmark`` 取真实 id 再逐个 ``hm_getvalue``，
    比 ``hm_allentitiesinfo`` 可靠——后者的返回结构随实体类型变化（comps 会带
    ``1 1 7 0 -1`` 之类的附加字段，按空白切分配对会错位）。
    """
    _ensure(s)
    etype = a.get("entity_type", "comps")
    raw = s.call(
        f"set o {{}}; "
        f"if {{[catch {{*createmark {etype} 1 all}} e]}} {{ return -code error $e }}; "
        f"foreach i [hm_getmark {etype} 1] {{ "
        f"lappend o \"$i\\t[hm_getvalue {etype} id=$i dataname=name]\" }}; "
        f"join $o \"\\n\""
    )
    pairs = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or "\t" not in line:
            continue
        eid, name = line.split("\t", 1)
        pairs.append({"id": int(eid), "name": name})
    return {"ok": True, "entity_type": etype, "count": len(pairs), "entities": pairs[:500]}


def t_run_tcl(s: HMSession, a: dict) -> dict:
    script = a.get("script") or ""
    if not script.strip():
        raise HMError("script 不能为空")
    out = s.call(script, timeout=900)
    return {"ok": True, "result": out}


_MIDMESH_STATS = r"""
set __o {}
for {set c __FIRST__} {$c <= [hm_entitymaxid comps]} {incr c} {
    if {[catch {hm_getvalue comps id=$c dataname=name} __nm]} { continue }
    if {$__nm eq ""} { continue }
    *createmark elems 2 "by comps" $__nm
    lappend __o "$c\t$__nm\t[hm_marklength elems 2]"
    *clearmark elems 2
}
join $__o "\n"
"""


def t_midmesh(s: HMSession, a: dict) -> dict:
    """从实体（或曲面组）抽取中面并直接生成中面网格。

    **入口命令是 ``*midmesh_extract <etype> <mark> <elemsize>``**，这是 2021.2 的
    MidMesh 引擎。绕了很多弯路才定位到它：

    * ``*midsurface_extract_10 ...``（老版中面）对规整板件会报
      "Unable to construct the midsurface"，且在 GUI 会话里这个错误被吞成返回码 0；
    * ``*midmesh_extract`` 必须把 **实体类型和 mark id 都写全**，
      只传 ``<mark> <size>`` 或 ``comps ...`` 都会静默失败。

    200×200×4 实体、10mm 实测：输出 ``Midmesh.1``（400 个 quad4，正好 20×20）
    + ``^MidmeshEdges.1``（80 个 1D 边单元，周长 800/10），节点全部落在 z=2.000
    （板厚正中），源组件不被改动。
    """
    _ensure(s)
    size = float(a.get("element_size", 10.0))
    etype = (a.get("entity_type") or "solids").lower()
    if etype not in ("solids", "surfs"):
        raise HMError("entity_type 只支持 solids / surfs")
    if size <= 0:
        raise HMError("element_size 必须为正数")

    first_comp = int(s.call("hm_entitymaxid comps") or 0) + 1
    marked = int(
        s.call(f'*createmark {etype} 1 "displayed"; hm_marklength {etype} 1') or 0
    )
    if marked == 0:
        raise HMError(f"当前没有显示中的 {etype}，无法抽取中面")

    s.call(f"*midmesh_extract {etype} 1 {_num(size)}", timeout=1800)

    raw = s.call(_MIDMESH_STATS.replace("__FIRST__", str(first_comp)))
    comps: list[dict] = []
    for line in (raw or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        cid, name, n = parts
        try:
            comps.append({"id": int(cid), "name": name, "elems": int(n)})
        except ValueError:
            continue

    face_elems = sum(c["elems"] for c in comps if not c["name"].startswith("^"))
    edge_elems = sum(c["elems"] for c in comps if c["name"].startswith("^"))
    if not comps:
        raise HMError("MidMesh 返回成功但未生成新组件，请检查输入实体是否为闭合板状体")

    return {
        "ok": True,
        "element_size": size,
        "source": {"entity_type": etype, "count": marked},
        "components": comps,
        "face_elems": face_elems,
        "edge_elems": edge_elems,
        "message": f"中面网格 {face_elems} 个 2D 单元 + {edge_elems} 个边单元",
    }


# --------------------------------------------------------------------- 工具表

def _p(desc: str, **extra) -> dict:
    d = {"type": "string", "description": desc}
    d.update(extra)
    return d


TOOLS: list[dict] = [
    {
        "name": "hm_status",
        "description": "查看 HyperMesh 会话状态与模型实体计数（profile、comp/mat/prop/elem/node 等）。每次连接后建议先调用一次。",
        "inputSchema": {"type": "object", "properties": {}},
        "impl": t_status,
    },
    {
        "name": "hm_new_model",
        "description": "清空当前模型并建立默认 component，用于开始一个新算例。",
        "inputSchema": {
            "type": "object",
            "properties": {"component": _p("默认 component 名称，缺省 unsorted")},
        },
        "impl": t_new_model,
    },
    {
        "name": "hm_open_model",
        "description": "打开已有的 .hm 模型文件（会替换当前模型）。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": _p("绝对路径，如 F:/work/bracket.hm")},
            "required": ["path"],
        },
        "impl": t_open_model,
    },
    {
        "name": "hm_save_model",
        "description": "把当前模型保存为 .hm 文件。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": _p("绝对路径；缺省保存到工作目录 model.hm")},
        },
        "impl": t_save_model,
    },
    {
        "name": "hm_model_summary",
        "description": "只返回实体计数（比 hm_status 更轻）。",
        "inputSchema": {"type": "object", "properties": {}},
        "impl": t_summary,
    },
    {
        "name": "hm_create_component",
        "description": "建立一个 component（同名已存在则复用）。",
        "inputSchema": {
            "type": "object",
            "properties": {"name": _p("component 名称")},
            "required": ["name"],
        },
        "impl": t_create_component,
    },
    {
        "name": "hm_create_plane_surface",
        "description": "在原点生成一块正方形平面曲面，用于无 CAD 时的演示或基准板件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "size": {"type": "number", "description": "边长（模型单位），缺省 100"},
                "normal": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "法向 [nx,ny,nz]，缺省 [0,0,1]",
                },
            },
        },
        "impl": t_create_plane,
    },
    {
        "name": "hm_mesh_surfaces",
        "description": "对当前显示的曲面做 2D 自动网格划分，尺寸由 element_size 精确控制（实测误差 0）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_size": {"type": "number", "description": "目标单元尺寸，缺省 10"},
                "element_type": {"type": "integer", "description": "2=四边形(缺省)，1=三角形"},
            },
        },
        "impl": t_mesh,
    },
    {
        "name": "hm_midmesh_extract",
        "description": "对显示中的实体抽取中面并直接生成中面网格（2021.2 MidMesh 引擎）。输出到新建的 Midmesh.N / ^MidmeshEdges.N 组件，源实体不动。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_size": {"type": "number", "description": "中面网格尺寸，缺省 10"},
                "entity_type": _p("输入类型：solids（缺省，实体）/ surfs（曲面组）"),
            },
        },
        "impl": t_midmesh,
    },
    {
        "name": "hm_create_material",
        "description": "建立 MAT1 材料并写入 E / Nu / Rho（已存在同名则更新数值）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _p("材料名，缺省 Steel"),
                "E": {"type": "number", "description": "弹性模量，缺省 210000"},
                "nu": {"type": "number", "description": "泊松比，缺省 0.3"},
                "rho": {"type": "number", "description": "密度，缺省 7.85e-9"},
            },
        },
        "impl": t_create_material,
    },
    {
        "name": "hm_create_property",
        "description": "建立 PSHELL 属性（壳厚度），可同时关联材料。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _p("属性名，缺省 Plate"),
                "thickness": {"type": "number", "description": "壳厚度，缺省 1.0"},
                "material": _p("材料名；给出则设置 PSHELL 的材料引用（MID1）"),
            },
        },
        "impl": t_create_property,
    },
    {
        "name": "hm_assign_property",
        "description": "把属性赋给 component。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "component": _p("component 名称"),
                "property": _p("属性名"),
            },
            "required": ["component", "property"],
        },
        "impl": t_assign_property,
    },
    {
        "name": "hm_create_loadcollector",
        "description": "建立载荷集（load collector）并设为当前，后续载荷会写进去。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _p("载荷集名称"),
                "make_current": {"type": "boolean", "description": "是否设为当前，缺省 true"},
            },
            "required": ["name"],
        },
        "impl": t_create_loadcollector,
    },
    {
        "name": "hm_add_constraints",
        "description": "在节点上加约束（SPC）。dofs 用 1~6 表示 Tx/Ty/Tz/Rx/Ry/Rz。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "loadcollector": _p("载荷集名称"),
                "nodes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "节点 id 列表；省略或空表示全部节点",
                },
                "dofs": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "约束自由度，缺省 [1,2,3]",
                },
            },
            "required": ["loadcollector"],
        },
        "impl": t_constraints,
    },
    {
        "name": "hm_add_force",
        "description": "在节点上加集中力/力矩（FORCE）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "loadcollector": _p("载荷集名称"),
                "nodes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "节点 id 列表；省略表示全部节点",
                },
                "fx": {"type": "number", "description": "X 向力"},
                "fy": {"type": "number", "description": "Y 向力"},
                "fz": {"type": "number", "description": "Z 向力"},
                "mx": {"type": "number", "description": "X 向力矩"},
                "my": {"type": "number", "description": "Y 向力矩"},
                "mz": {"type": "number", "description": "Z 向力矩"},
            },
            "required": ["loadcollector"],
        },
        "impl": t_force,
    },
    {
        "name": "hm_create_loadstep",
        "description": "建立工况（loadstep/SUBCASE），引用约束载荷集与载荷集。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _p("工况名，缺省 static1"),
                "spc_loadcollector": _p("约束载荷集名称"),
                "load_loadcollector": _p("载荷集名称"),
            },
        },
        "impl": t_loadstep,
    },
    {
        "name": "hm_export",
        "description": "导出求解器 deck（默认 OptiStruct .fem），并返回 deck 体检报告。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _p("输出文件绝对路径；缺省工作目录 model.opt"),
                "solver": _p("optistruct | nastran | abaqus | radioss | lsdyna，缺省 optistruct"),
            },
        },
        "impl": t_export,
    },
    {
        "name": "hm_deck_report",
        "description": "解析已导出的 deck 文件，统计卡片数量并列出 case control 行（不需要 HyperMesh 在线）。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": _p("deck 文件绝对路径")},
            "required": ["path"],
        },
        "impl": t_deck_report,
    },
    {
        "name": "hm_find_entities",
        "description": (
            "按空间位置找出节点/单元/曲面的 id，用于给约束和载荷定位（代替猜 id）。"
            "mode=box 是体积选区（min/max 包围盒），要做平面选区就传一个薄盒（厚度方向 ±容差）；"
            "mode=sphere 取球面壳上的实体（不是球体内部）。inside=false 可反选。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": _p("box（缺省）| sphere"),
                "entity_type": _p("nodes（缺省）| elems | surfaces"),
                "min": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "box 模式：包围盒最小角 [x,y,z]",
                },
                "max": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "box 模式：包围盒最大角 [x,y,z]",
                },
                "center": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "sphere 模式：球心 [x,y,z]",
                },
                "radius": {"type": "number", "description": "sphere 模式：半径"},
                "inside": {"type": "boolean", "description": "true=选区内（缺省），false=反选"},
                "limit": {"type": "integer", "description": "最多返回多少个 id，缺省 200"},
                "with_coords": {
                    "type": "boolean",
                    "description": "entity_type=nodes 时是否附带坐标，缺省 false",
                },
            },
        },
        "impl": t_find_entities,
    },
    {
        "name": "hm_list_entities",
        "description": "列出某类实体的 id 与名称，用于取节点/实体 id（comps / mats / props / loadcols / loadsteps）。",
        "inputSchema": {
            "type": "object",
            "properties": {"entity_type": _p("comps | mats | props | loadcols | loadsteps，缺省 comps")},
        },
        "impl": t_list_entities,
    },
    {
        "name": "hm_run_tcl",
        "description": "直接执行任意 HyperMesh Tcl（逃生口）。用于本工具集未覆盖的面板操作；多行脚本会自动压成单行。",
        "inputSchema": {
            "type": "object",
            "properties": {"script": _p("要执行的 Tcl 脚本")},
            "required": ["script"],
        },
        "impl": t_run_tcl,
    },
]

BY_NAME = {t["name"]: t for t in TOOLS}
