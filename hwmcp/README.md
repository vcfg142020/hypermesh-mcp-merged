# HyperMesh MCP Server

用 MCP（Model Context Protocol）协议让 AI 驱动 Altair HyperMesh 完成前处理：建几何、划网格、设材料/属性/载荷/工况、导出求解器 deck。

面对的是**真实的本机 HyperMesh 进程**，不是模拟器。所有 Tcl 命令签名都在 HyperWorks 2021.2 + OptiStruct profile 上实测验证过。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| HyperWorks | 2021.2（实测 2021.2.0.31），装在 `F:\Program\Altair2021.2` |
| Python | 3.9+，**无需任何第三方包**（纯标准库） |
| 可执行文件 | `hwdesktop\hm\bin\win64\hmopengl.exe`（GUI 版，**不能用 hmbatch.exe**） |

> **为什么必须用 GUI 版**：`hmbatch.exe` 在 `-tcl` 批处理模式下 `g_profile_name` 恒为 `HyperMesh`，
> 求解器 profile 不加载，`MAT1`/`PSHELL` 卡片定义缺失，`*setvalue mats id=1 E=210000` 直接报
> `Invalid input`。改成 `hmopengl.exe` 后 profile 变为 `OptiStruct`，一切正常。
> `-nouser`、`IUserprofile`、`hm_trackuserprofile` 等方式都无法绕过。

---

## 2. 安装与启动

```bash
cd F:/Program/WorkbuddyFiles/hyperworks/hwmcp

python doctor.py     # 环境自检：逐项确认能不能用（接入前先跑这个）
python _e2e.py       # 端到端自检：建板 → 划网格 → 材料属性 → 载荷工况 → 导出 deck
python server.py     # 以 stdio 方式运行 MCP server（供客户端调用）
python _cli.py '<tcl>'   # 手工调试：把一条 Tcl 发进常驻会话
```

> 第一次接入请直接看 **`CONFIG_GUIDE.md`**，那是按步骤走的配置教程，每步都有预期输出可对照。

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HWMCP_HM_EXE` | `F:\Program\Altair2021.2\hwdesktop\hm\bin\win64\hmopengl.exe` | HyperMesh 可执行文件 |
| `HWMCP_PORT` | 自动取空闲端口 | 固定 socket 端口（多实例调试用） |
| `HWMCP_AUTOSTART` | `1` | server 启动时预拉起 HyperMesh；设 `0` 改为首次调用时懒启动 |
| `HWMCP_STARTUP_TIMEOUT` | `180` | 等待 HyperMesh 就绪的秒数 |
| `HWMCP_WORKDIR` | 脚本所在目录 `workspace/` | 模型与 deck 的默认输出目录 |

首次启动约 15–20 秒（HyperMesh 初始化），之后所有工具调用是毫秒级。

---

## 3. 接入 WorkBuddy

写入 `~/.workbuddy/mcp.json`（**不是** `.mcp.json`）：

```json
{
  "mcpServers": {
    "hypermesh": {
      "command": "python",
      "args": ["F:/Program/WorkbuddyFiles/hyperworks/hwmcp/server.py"],
      "env": {
        "HWMCP_AUTOSTART": "1"
      }
    }
  }
}
```

保存后在连接器管理页右上角的「自定义连接器」里对新条目点**信任**才会生效。

---

## 4. 工具速查

### 会话与模型

| 工具 | 作用 |
|---|---|
| `hm_status` | 会话状态 + 实体计数（profile、comp/mat/prop/elem/node…），**每次连上先调一次** |
| `hm_new_model` | 清空模型并建默认 component |
| `hm_open_model` | 打开已有 `.hm` |
| `hm_save_model` | 保存 `.hm` |
| `hm_model_summary` | 只返回计数，比 `hm_status` 更轻 |

### 几何与网格

| 工具 | 作用 |
|---|---|
| `hm_create_component` | 建 component（同名复用） |
| `hm_create_plane_surface` | 在原点建正方形平面（无 CAD 时的基准板） |
| `hm_mesh_surfaces` | 曲面 2D 网格，`element_size` 精确控制尺寸 |
| `hm_midmesh_extract` | 实体抽中面并直接出中面网格（MidMesh 引擎），输出到 `Midmesh.N` / `^MidmeshEdges.N` |
| `hm_find_entities` | 按空间位置找节点/单元/曲面 id |

### 材料与属性

| 工具 | 作用 |
|---|---|
| `hm_create_material` | MAT1，写 E / Nu / Rho |
| `hm_create_property` | PSHELL，写厚度、可关联材料 |
| `hm_assign_property` | 属性赋给 component |

### 载荷与工况

| 工具 | 作用 |
|---|---|
| `hm_create_loadcollector` | 建载荷集并设为当前 |
| `hm_add_constraints` | SPC，`dofs` 用 1–6 表示 Tx/Ty/Tz/Rx/Ry/Rz |
| `hm_add_force` | FORCE，可给 6 个分量（含力矩） |
| `hm_create_loadstep` | 建 SUBCASE，绑定 SPC 与 LOAD 载荷集 |

### 导出与逃生口

| 工具 | 作用 |
|---|---|
| `hm_export` | 导出 deck（optistruct/nastran/abaqus/radioss/lsdyna）+ 体检报告 |
| `hm_deck_report` | 离线解析 deck：卡片计数 + case control 行 |
| `hm_list_entities` | 列实体 id 与名称 |
| `hm_run_tcl` | 直接执行任意 Tcl（未覆盖的面板操作用这个） |

---

## 5. 典型流程

```
1. hm_status                          # 确认进程与 profile=OptiStruct
2. hm_new_model      component=plate
3. hm_create_plane_surface  size=200
4. hm_mesh_surfaces  element_size=10  # → 400 单元 / 441 节点
5. hm_create_material name=Steel E=210000 nu=0.3 rho=7.85e-9
6. hm_create_property name=Plate thickness=2.0 material=Steel
7. hm_assign_property component=plate property=Plate
8. hm_find_entities  mode=box min=[-101,-101,-1] max=[-99,101,1]   # 左边界 21 个节点
9. hm_create_loadcollector name=SPC_LC
10. hm_add_constraints loadcollector=SPC_LC nodes=[41,42,43,44,45] dofs=[1,2,3]
11. hm_create_loadcollector name=FORCE_LC
12. hm_find_entities mode=box min=[-6,-6,-1] max=[6,6,1] with_coords=true
13. hm_add_force     loadcollector=FORCE_LC nodes=[90] fz=-100
14. hm_create_loadstep name=static1 spc_loadcollector=SPC_LC load_loadcollector=FORCE_LC
15. hm_export        path=F:/work/plate.fem solver=optistruct
```

第 15 步返回的 `report` 里应当看到：

```json
{
  "counts": {"GRID": 441, "CQUAD4": 400, "PSHELL": 1, "MAT1": 1, "SPC": 5, "FORCE": 1, "SUBCASE": 1},
  "case_control": ["SUBCASE        1", "LABEL static1", "SPC =        1", "LOAD =        2"]
}
```

---

## 6. 架构

```
MCP client ──stdio JSON-RPC──> server.py ──TCP 127.0.0.1:<auto>──> HyperMesh 进程
                                  │                                    ▲
                                  └── hm_session.py ── 启动 hmopengl.exe -tcl _sock.tcl
```

前处理是有状态的，不能每条命令起一个进程。做法是把 `_sock.tcl` 注入 HyperMesh，让进程自己监听
TCP：一行命令进、一行结果出（`OK: ...` / `ERR: ...`），`__PING__` 探活、`__EXIT__` 退出。
多行 Tcl 由 `to_single_line()` 压成单行传输。

---

## 7. 故障排查

| 现象 | 原因与处置 |
|---|---|
| `Invalid input` on `*setvalue mats ...` | 用了 `hmbatch.exe`，profile 未加载。换成 `hmopengl.exe` |
| `FatalError: Invalid interactive routine called while in batch mode` | `*deletemodel` 前少了 `hm_answernext yes;` |
| `can't create procedure ...: unknown namespace` | Tcl 过程定义用了不存在的命名空间，改用全局过程 |
| 工具全部报通信失败 | HyperMesh 进程崩了；`taskkill /F /IM hmopengl.exe` 后重试，会话会自动重启 |
| 启动超过 3 分钟 | 检查 `hmcustom.tcl`（`Wuzheng_Code_20230410/`）是否报错；GUI 模式下它一般无碍 |
| deck 里没有 `SPC =` / `LOAD =` | 工况没绑好。`*loadstepscreate` 只建空壳，必须补属性 4143–4147，见 `HANDOFF.md` |
| 导出的 `.hm` 读不出明文 | 本机 E-SafeNet 透明加密；但 `*feoutputwithdata` 导出的 `.fem` 是明文 |

---

## 8. 已验证的边界

- **能**：平面板件 2D 网格、MAT1/PSHELL、SPC/FORCE、单工况、四种求解器导出
- **不能**（尚未实现）：读 CAD 文件（STEP/IGES）、3D 实体网格、接触/连接、多工况批处理、结果后处理
- **注意**：`hm_mesh_surfaces` 只处理**当前显示**的曲面；`hm_add_constraints` / `hm_add_force` 省略
  `nodes` 会把载荷加到**全部节点**上（适合快速试算，正式算例务必给显式 id 列表）

细节与调试记录见 `HANDOFF.md`，分步配置教程见 `CONFIG_GUIDE.md`。
