# HWMCP 交接文档（Handoff）

> 目标：用 MCP 协议让 AI 驱动 Altair HyperMesh 2021.2 完成前处理。
> 状态：**核心链路已跑通并通过端到端验证**，用户文档已补齐。
> 最后更新：2026-11-13 12:05

---

## 1. 文件清单

| 文件 | 行数 | 作用 |
|---|---|---|
| `server.py` | 198 | MCP server 主程序，stdio JSON-RPC 2.0，零第三方依赖 |
| `hm_session.py` | 203 | HyperMesh 进程 + socket 会话管理，自动取空闲端口 |
| `tools.py` | 825 | 20 个前处理工具的实现 + JSON Schema |
| `_sock.tcl` | 22 | 注入 HyperMesh 的常驻 TCP 服务端（**已验证，不要乱改**） |
| `_e2e.py` | 128 | 端到端测试，18 次工具调用，走完整前处理链路 |
| `_cli.py` | 24 | 手工调试客户端，交互式发 Tcl |
| `README.md` | 185 | 面向用户：安装、接入 mcp.json、20 工具速查、典型流程、故障排查 |

`workspace/` 下是 e2e 产物：`e2e_plate.hm`、`e2e_plate.fem`（49,748 B，441 GRID / 400 CQUAD4）。

---

## 2. 启动与验证

```bash
cd F:/Program/WorkbuddyFiles/hyperworks/hwmcp
python _e2e.py            # 完整验证，约 40s（含 HyperMesh 启动 15-20s）
python server.py          # 直接跑 MCP server（stdio）
python _cli.py            # 交互式发 Tcl 调试
```

环境变量：

- `HWMCP_EXE` —— 覆盖 HyperMesh 可执行文件路径（默认见下）
- `HWMCP_PORT` —— 固定 socket 端口（默认自动取空闲端口）
- `HWMCP_AUTOSTART` —— 默认 `1`，server 启动时预拉起 HyperMesh；设 `0` 则懒启动

---

## 3. 关键技术决策（踩过的坑，勿回退）

### 3.1 必须用 GUI 版 `hmopengl.exe`，不能用 `hmbatch.exe`

```
F:\Program\Altair2021.2\hwdesktop\hm\bin\win64\hmopengl.exe
```

| | hmbatch.exe -tcl | hmopengl.exe -tcl |
|---|---|---|
| `g_profile_name` | 恒为 `HyperMesh` | **`OptiStruct`** |
| 卡片定义 | 缺失 | 完整 |
| `*setvalue mats id=1 E=210000` | `Invalid input` | 正常 |
| `dataname=cardimage` | `<None>` | `MAT1` |

`-nouser`、`IUserprofile`、`hm_trackuserprofile`、`hm_setuserprofileoption` 全试过，都无法在 batch 模式加载 solver profile。**GUI 模式是唯一可行路径。**

附带问题：`F:\Program\Altair2021.2\Wuzheng_Code_20230410\hmcustom.tcl` 第 12 行 `hm_framework getpulldowns` 在 batch 模式报 `Invalid args to hm_framework (batch mode)`，GUI 模式无此问题。

### 3.2 架构：常驻 socket 服务

前处理是有状态的，不能每条命令起一个进程。做法是把 `_sock.tcl` 用 `-tcl` 注入，HyperMesh 进程自己监听 TCP：

- 协议：一行命令进，一行结果出；`OK: <result>` / `ERR: <msg>`
- 控制字：`__PING__` → `OK: pong`；`__EXIT__` → `OK: bye` 后退出
- 结果里的换行被转义成 `\n`，Python 侧还原
- 多行 Tcl 由 `hm_session.to_single_line()` 压成单行（跳过空行与 `#` 注释，处理行尾 `\` 续行，用 `;` 连接）

### 3.3 命名空间陷阱（已修复）

`_BOOTSTRAP` 里曾写 `proc ::hwmcp::count`，但 `::hwmcp` 命名空间不存在 → 19 个工具全部报
`can't create procedure "::hwmcp::count": unknown namespace`。
现改为**全局过程 `__hwmcp_count`**，不依赖任何命名空间。改动点在 `tools.py` 的 `_BOOTSTRAP` 与 `t_status`。

### 3.4 `*deletemodel` 必须先 `hm_answernext yes`

否则 batch 模式 `FatalError: Invalid interactive routine called while in batch mode`，socket 被 reset。
正确写法：`hm_answernext yes; *deletemodel; ...`

---

## 4. 实测通过的命令签名（全部来自本机 OptiStruct profile）

```
# 建 component
*collectorcreateonly components "NAME" "" 7

# 建平面曲面
*surfacemode 4
*createplane 1 nx ny nz 0 0 0
*surfaceplane 1 <size>

# 2D 网格（推荐，尺寸精确）
*createmark surfaces 1 "displayed"
*defaultmeshsurf 1 <size> <etype> 0 2 0 0 1 1 0 0 0 0
# 签名：markmask elem_size elem_type elem_type2 forcing elemstosurfcomp
#       size_control skew_control edge_mesh_type min_size max_size chordal_div max_angle
# 出处：hm/scripts/HyperXtrude/layered_ew_g3m.tcl 第 204 行注释
# 自带落库，不需要 *storemeshtodatabase；200 板实测 20/10/5/2 → 100/400/1600/10000 单元
# ⚠ 不要用 *interactiveremeshsurf + *set_meshfaceparams + *automesh 那套面板流程：
#   尺寸会被面板状态吞掉（传 10 仍得 2mm），大尺寸会让 *automesh 挂起 90s+

# 材料 MAT1
*createentity mats name=X cardimage=MAT1
*setvalue mats id=<mid> E=... ; Nu=... ; Rho=...
# 字段名：1=E, 2=G, 3=Nu, 4=Rho（hm_attributenamefromid <n> mats 可枚举）

# 属性 PSHELL
*createentity props name=X cardimage=PSHELL
*setvalue props id=<pid> 95=<T>          # 95 = PSHELL_T；写 T=2.0 无效
# 其它：113=MID2, 115=MID3, 119=Z1, 120=Z2, 121=MID4

# 材料关联（唯一有效写法！）
*setvalue props id=<pid> materialid={mats <mid>}
# MID1=1 / 832=1 / 437=1 / MAT1=1 / PSHELL=1 / hm_entity_setproperty 全部无效

# 属性赋予
*setvalue comps id=<cid> propertyid={props <pid>}

# 载荷集
*collectorcreate loadcols "NAME" "" 1
*currentcollector loadcols "NAME"

# 载荷/约束
*loadcreateonentity_curve nodes 1 <config> 1 <6 个值> 0 0 0 0 0
# config 1 = FORCE, config 2 = MOMENT, config 3 = SPC
# SPC 的 6 个值是各 DOF 的 0/1 标志；FORCE 的 6 个值是 Fx Fy Fz Mx My Mz

# 工况（最难点，缺 4143 就没 SPC=/LOAD=）
*loadstepscreate "<name>" 1
*initializeattributes loadsteps "<name>"
*attributeupdateint loadsteps <id> 3239 1 0 0 0
*attributeupdateint loadsteps <id> 3240 1 0 0 3
*attributeupdateint loadsteps <id> 4143 1 0 1 1            # 工况启用
*attributeupdateint loadsteps <id> 4144 1 0 1 1            # SPC 开关
*attributeupdateentity loadsteps <id> 4145 1 0 1 loadcols <spc_id>
*attributeupdateint loadsteps <id> 4146 1 0 1 1            # LOAD 开关
*attributeupdateentity loadsteps <id> 4147 1 0 1 loadcols <load_id>
# 属性号来源：hwdesktop/hm/scripts/loadstepbrowser/nastran/LoadstepOptions_LoadReferences.tcl
#             第 2017-2025、3718-3726 行

# 导出（参数含义见 hwdesktop/hw/tcl/hweFD/OrgPg.tcl 注释）
*feoutputwithdata "<tpl>" "<file>" 0 0 1 1 0
# export_template filename reserved1 reserved2 export_type string_array number_of_strings

# 保存 / 读取 / 清模型
*writefile "<path>" 0
*readfile "<path>"
hm_answernext yes; *deletemodel

# 实体枚举（比 hm_allentitiesinfo 可靠）
*createmark <type> 1 all
foreach i [hm_getmark <type> 1] { hm_getvalue <type> id=$i dataname=name }

# 空间选区（mark 方法）
*createmark nodes 1 "by box" xmin ymin zmin xmax ymax zmax 0 inside 0 0 0
#   ↑ 必须凑满 11 个参数；只给 6 个坐标时返回 1 但标记为空
*createmark nodes 1 "by sphere" cx cy cz r 0 inside 0 0 0
#   ↑ 球面壳，不是球体内部（r=10 得 4 个点，r=15 得 0）
# "by plane" 不可用：无论 5/6/7 个参数、容差 0.1 还是 20，都标记全部节点
```

**坑**：`hm_getvalue <type> name=X dataname=id` 对不存在的名字也返回 `1`。
`_id_by_name()` 因此先 `dataname=name` 回读校验存在性，再取 id。

---

## 5. 端到端验证结果（全绿）

`python _e2e.py`，18 次工具调用全部 `[ok]`：

```
hm_status / hm_new_model / hm_create_plane_surface(200) / hm_mesh_surfaces(10)
hm_create_material(Steel E=210000 nu=0.3) / hm_create_property(Plate t=2.0)
hm_assign_property
hm_find_entities(box 左边界) / hm_find_entities(box 中心 with_coords)
hm_find_entities(box y=0 薄盒) / hm_find_entities(sphere r=10)
hm_create_loadcollector(SPC_LC) / hm_add_constraints(21 个边界点中的 5 个 × 3 DOF)
hm_create_loadcollector(FORCE_LC) / hm_add_force(中心节点 fz=-100)
hm_create_loadstep(static1) / hm_list_entities / hm_save_model / hm_export / hm_status
```

模型规模：400 CQUAD4 / 441 GRID（element_size=10 精确命中）
选区验证：x=-100 边界 21 个节点、中心盒 1 个节点（原点）、y=0 薄盒 21 个、球面 r=10 得 4 个
导出 deck：49,748 字节，case control 段

```
SUBCASE        1
LABEL static1
SPC =        1
LOAD =        2
```

卡片计数：`GRID 441 / CQUAD4 400 / PSHELL 1 / MAT1 1 / SPC 5 / FORCE 1 / SUBCASE 1`

---

## 6. 21 个工具

`hm_status`、`hm_new_model`、`hm_open_model`、`hm_save_model`、`hm_model_summary`、
`hm_create_component`、`hm_create_plane_surface`、`hm_mesh_surfaces`、`hm_midmesh_extract`、
`hm_find_entities`、
`hm_create_material`、`hm_create_property`、`hm_assign_property`、
`hm_create_loadcollector`、`hm_add_constraints`、`hm_add_force`、`hm_create_loadstep`、
`hm_export`、`hm_deck_report`、`hm_list_entities`、`hm_run_tcl`

---

## 7. 剩余待办

1. **清理临时文件**：运行时会生成 `command*.tcl`、`_hm_session.log`，可随时删
2. 可选增强：读 CAD（STEP/IGES）、3D 实体网格、多工况批处理、结果后处理（HyperView）
3. BatchMesher 尚未封装（CLI 已验证可用，见 7.2）

---

## 7.2 MidMesh / BatchMesher 能力边界（2026-11-16 实测）

这两项原先都不在工具集里，实测后结论分开：**MidMesh 已打通并封装**，**BatchMesher 只能命令行驱动、未封装**。

### ① MidMesh：入口是 `*midmesh_extract <etype> <mark> <elemsize>`

四个必备要素，缺一个就静默失败（返回 0 或 error message 为 `0`，没有任何提示）：

1. **实体类型要显式写出**：`*midmesh_extract solids 1 10`，只传 `<mark> <size>` 会失败
2. mark 里要有显示中的实体：先 `*createmark solids 1 "displayed"`
3. 尺寸是第 3 个参数
4. 输入必须是**闭合板状体**（有厚度的 solid）

实测（200×200×4 板，10mm）：

```
输出组件：Midmesh.1（400 个 quad4 = 20×20，精确）
          ^MidmeshEdges.1（80 个 1D 边单元 = 周长 800/10，精确）
节点坐标：441 个节点全部 z = 2.000（板 0~4 的正中）
源组件：plate 保持不变，0 单元
```

对照组——**老版中面命令不能用**：

```
*midsurface_extract_10 solids 1 3 0 1 1 3 0 20 0 0 10 0 10 -2 undefined 0 0 0
→ 批处理下打印 "Error: Unable to construct the midsurface"，GUI 会话里只剩返回码 0
（参数是从 Altair 自带脚本 AirframeMesh.tcl:1575 原样抄的，不是参数写错，
 是这条老命令对规整板件本来就构不出中面）
```

**排查方法论**：GUI 会话里 `*`-命令失败时只回一个 `0`，看不出原因。
把同样的调用写成 Tcl 脚本用 `hmbatch.exe -tcl xxx.tcl` 跑，**stderr 会打印真实错误文本**
（"Unable to construct the midsurface" 就是这么看到的）。这是排查 `*` 命令的首选手段。

### ② BatchMesher：独立程序，只能走 CLI

不是 HM 内的命令，是 JRE + jar：`hwdesktop/hm/batchmesh/hw_batchmesh.bat`。

```bash
hw_batchmesh.bat -nogui \
  -cad_model_file <输入.hm> -cad_translator hm \
  -criteria_file .../general_10mm.criteria \
  -param_file   .../general_10mm.param \
  -work_dir <输出目录> -run_results <results.txt>
```

实测 200×200×4 实体块：1 秒完成，产出结果 `.hm`（可被 `hm_open_model` 打开）+ `results.txt` 质量表 +
每模型 `_res.txt` 分步记录。但结果是 18 单元 / 90.9% 三角 / quality index 1939 —— 裸实体块是病态输入，
BatchMesher 的自动清理面向真实 CAD 零件，跑通 ≠ 好用。

**坑**：`-batch` 是 GUI 自动化（要配 `-config_file`），和 `-nogui` 混用会直接打印 usage 退出。

### ③ bootstrap 必须按连接世代重注入

`HMSession._gen` 在每次新建 socket 时自增，`tools._ensure()` 比对这个世代号决定是否重发
`_BOOTSTRAP`。只用一个布尔标记的话，HyperMesh 崩溃自动重启后，新进程里没有
`__hwmcp_count`，`hm_status` 等工具会报 `invalid command name "__hwmcp_count"`。

---

## 7.1 接入客户端时踩的三个坑（2026-11-16，已全部修复）

这三个坑都不会在本地 `python _e2e.py` 中暴露，只有通过 MCP 客户端拉起进程时才出现。

### ① `main()` 在进入 stdin 循环前同步启动 HyperMesh → 握手超时

原实现先 `get_session().start()`（15-25 秒）再 `for line in sys.stdin`，客户端发 `initialize`
时无人应答，直接判 `MCP error -32000: Connection closed`（日志显示 `connectMs=153`）。

修法：预启动移到 daemon 线程，握手立即返回。实测 `initialize` 从超时降到 **278 ms**。

```python
threading.Thread(target=_prestart_hypermesh, name="hwmcp-prestart", daemon=True).start()
```

### ② `_sock.tcl` 的 `flush stdout` 中断整个脚本

报错：`can not find channel named stdout` / `Command line Tcl script read failed`。
客户端拉起的进程没有控制台，HyperMesh 的 stdout 一旦不可用，`flush stdout` 抛错导致
`socket -server` 虽然建了但脚本中止，客户端连上就被关。

修法两处：
- `_sock.tcl` 把 `puts/flush stdout` 包进 `catch`（端口本来就由 `HWMCP_PORT` 传入，不依赖这行输出）
- `hm_session.start()` 把 HyperMesh 的 stdout/stderr 从 `DEVNULL` 改为 `_hm_session.log`，
  既保证通道有效，也留下排查线索

### ③ 锁顺序死锁（由 ① 的修复引入）

预热线程持 `_start_lock` 等 `_io_lock`，工具调用线程持 `_io_lock` 等 `_start_lock`，
表现为首次工具调用永久挂起（>300 秒）。

修法：`_call_raw()` 先 `start()` 再取 `_io_lock`，`_start_locked()` 内部不再调 `_call_raw` 前持锁；
`_io_lock` 用 `RLock`（启动流程会重入 `self.call()`）。

### ④ `command: "python"` 不可靠

客户端子进程的 PATH 与终端不同，Windows 下 `python` 可能解析到 `WindowsApps\python.exe`
商店存根，启动后立刻退出。`mcp.json` 必须写绝对路径：

```
C:/Users/2025057553/.workbuddy/binaries/python/versions/3.13.12/python.exe
```

### 验证方法

`_handshake.py`（已删，可重建）模拟客户端：先 `initialize` 量耗时（应 < 1 s），
再调 `hm_status` 量首次等待（应 15-25 s）。改完这三处后：`initialize` 278 ms、
`hm_status` 21.3 s、完整 `_e2e.py` 20 次调用全过。

---

## 8. 其它环境事实

- E-SafeNet 透明加密：`*writefile` 出的 `.hm`、Tcl `open/puts` 出的文件可能被加密；
  但 `*feoutputwithdata` 导出的 `.fem` **是明文**（文件头 `$$\r\n$$ Optistruc`），可直接解析
- 安装版本：HyperWorks 2021.2.0.31，根目录 `F:\Program\Altair2021.2`
- 导出模板路径：`<root>/hwdesktop/templates/feoutput/` 下，支持 optistruct / nastran / abaqus / radioss / lsdyna
- 参考的官方脚本（只读）：`hm/examples/hm_extapi/hmtcl/blockmesh.tcl`（完整 2D 网格配方）

---

## 9. 同项目另一条线（阶段一，已完成）

`F:\Program\WorkbuddyFiles\hyperworks\out\` 下有 HyperWorks 2021.2 前处理/后处理功能详解文档：

- `HyperWorks_2021.2_前处理与后处理功能详解.docx`（106 页 / 41,565 字 / 520 链接）
- `mindmap.html` / `mindmap.md` / `mindmap.png`
- 源码在 `content/*.md`（12 个）、`build/*.py`

与该 MCP 项目相互独立，勿混。
