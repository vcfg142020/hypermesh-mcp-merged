# HyperMesh MCP — 集成交接说明

给「另一个会话 / 另一个 MCP 客户端」用的集成说明。目标读者是一个不了解本项目的 AI 助手。

---

## 0. 一句话说清它是什么

一个 **stdio 传输的 MCP server**（JSON-RPC 2.0，逐行），把一台 Windows 机器上的
**Altair HyperWorks 2021.2 / HyperMesh** 封装成 21 个工具：建模、划网格、赋材料属性、
加约束载荷、建工况、导出求解器 deck。它通过常驻 socket 驱动一个 GUI 版 `hmopengl.exe`
进程，**不是**脚本级调用 `hmbatch`。

- 代码目录：`<仓库路径>/hwmcp`
- 入口脚本：`server.py`
- 纯 Python 标准库实现，无需 pip 安装任何依赖（Python ≥ 3.10）
- 平台：仅 Windows（依赖本地 HyperWorks 安装）

---

## 1. 直接可用的配置片段（通用 stdio 格式）

```json
{
  "mcpServers": {
    "hypermesh": {
      "command": "python",
      "args": ["<仓库路径>/hwmcp/server.py"],
      "env": {
        "HWMCP_AUTOSTART": "1",
        "HWMCP_HM_VERSION": "2021.2"
      }
    }
  }
}
```

`command` 必须是 **Python 解释器的绝对路径**。Windows 上写 `"python"` 可能命中
`WindowsApps\python.exe` 商店存根（启动即退出，表现为 `MCP error -32000: Connection closed`）。

### 环境变量

| 变量 | 必需 | 说明 |
|---|---|---|
| `HWMCP_HM_EXE` | 建议显式给 | `hmopengl.exe` 绝对路径。不给则用内置默认值 |
| `HWMCP_AUTOSTART` | 否 | `1`（缺省）启动即后台预热 HyperMesh；`0` 则首次工具调用才启动 |
| `HWMCP_STARTUP_TIMEOUT` | 否 | 预热等待秒数，缺省 180 |
| `HWMCP_WORKDIR` | 否 | 默认输出目录，缺省 `hwmcp/workspace` |
| `HWMCP_PORT` | 否 | 固定 socket 端口，缺省自动挑空闲端口 |

### 各客户端配置位置

| 客户端 | 文件 |
|---|---|
| WorkBuddy | `C:\Users\<用户>\.workbuddy\mcp.json` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |
| VS Code (Cline/Roo) | 扩展设置里的 MCP Servers JSON |

---

## 2. 集成后必须做的三步验收

### ① 工具清单必须是 21 个

调 `tools/list`，`hm_` 开头的工具应恰好 21 个：

```
hm_status  hm_new_model  hm_open_model  hm_save_model  hm_model_summary
hm_create_component  hm_create_plane_surface  hm_mesh_surfaces  hm_midmesh_extract
hm_find_entities  hm_list_entities
hm_create_material  hm_create_property  hm_assign_property
hm_create_loadcollector  hm_add_constraints  hm_add_force  hm_create_loadstep
hm_export  hm_deck_report  hm_run_tcl
```

少于 21 个说明加载的是旧代码，或配置文件未生效。

### ② 握手必须快，首次工具调用必须慢

- `initialize` → `tools/list`：应在 **1 秒内**完成。若超时 20 秒以上，说明预热被放在主线程，
  客户端会判 `-32000 Connection closed`。
- 第一次调 `hm_status`：**15–25 秒**是正常的（此时才真正拉起 HyperMesh）。

### ③ `hm_status` 的返回必须长这样

```json
{
  "running": true,
  "port": 6713,
  "exe": "<自动发现，或设 HWMCP_HM_EXE>",
  "profile": "OptiStruct",
  "entities": {"comps": 0, "mats": 0, "props": 0, "loadcols": 0, "loadsteps": 0,
               "elems": 0, "nodes": 0, "surfaces": 0, "solids": 0}
}
```

**`"profile": "OptiStruct"` 是唯一有效的验收信号。** 如果显示 `HyperMesh`，
说明跑的是 `hmbatch.exe` 而不是 GUI 版，后续所有材料/属性/工况命令都会报
`Invalid input`，必须换可执行文件。

---

## 3. 六个已知坑（都踩过，都修了，别回退）

1. **必须 `hmopengl.exe`，不能用 `hmbatch.exe`**
   batch 模式下 `g_profile_name` 恒为 `HyperMesh`，OptiStruct 卡片定义不加载。

2. **`command` 写绝对路径**，理由见第 1 节。

3. **改了代码或 `mcp.json` 之后，必须完全退出客户端再重开**
   WorkBuddy 关窗口只是最小化到托盘，MCP 列表只在进程启动时扫描一次。
   必须托盘右键「退出」。

4. **不要在多处同时启用**
   每个客户端会各自 spawn 一个 server 进程 → 各自拉起一个 HyperMesh GUI 实例
   → 占多份 license，且两个实例的模型互不相通。要换客户端用，先关掉旧的。

5. **别用 `grep` 读导出的 `.fem`**
   本机装了 E-SafeNet 透明加密：同一个 `.fem`，MCP 里的 Python 读到明文，
   Git Bash 的 `grep` 读到密文乱码。检查 deck 内容一律用 Python，或调 `hm_deck_report`。

6. **HyperMesh 崩溃后会自动重启**
   server 侧按「连接世代」重注入 Tcl 辅助过程。若你看到
   `invalid command name "__hwmcp_count"`，说明跑的是旧版本代码，重启 MCP 即可。

---

## 4. 自检与排障

```bash
# 10 项环境自检（会真的启动一次 HyperMesh、建 component、建曲面）
python \
  <仓库路径>/hwmcp/doctor.py
```

预期 10/10 通过。任一项失败会直接指出是 Python、可执行文件、注入脚本还是 profile 的问题。

| 日志 | 内容 |
|---|---|
| `hwmcp/_hm_session.log` | HyperMesh 进程自身的 stdout/stderr（启动横幅、Tcl 报错） |
| MCP server 的 stderr | server 侧日志（`started, python=...`、`HyperMesh ready on port ...`） |
| `~/.workbuddy/logs/` | WorkBuddy 客户端侧连接日志，搜 `MCP-ManagerConnect` |

排障顺序：先看客户端日志有没有 `state=ready / success=true`，再看 `_hm_session.log`
里有没有 `HWMCP_LISTEN`，最后才怀疑工具实现。

---

## 5. 典型调用顺序（照着跑能验证整条链路）

```
hm_status                                    # 确认 profile=OptiStruct
hm_new_model(component="plate")              # 清空 + 建默认 comp
hm_create_plane_surface(size=200)            # 200×200 基准板
hm_mesh_surfaces(element_size=10)            # → 400 个 CQUAD4 / 441 个 GRID
hm_create_material(name="Steel", E=210000, nu=0.3, rho=7.85e-9)
hm_create_property(name="Plate", thickness=2.0, material="Steel")
hm_assign_property(component="plate", property="Plate")
hm_find_entities(mode="box", min=[-101,-101,-1], max=[-99,101,1])   # 左边界 21 个节点
hm_create_loadcollector(name="SPC_LC")
hm_add_constraints(loadcollector="SPC_LC", nodes=[...], dofs=[1,2,3])
hm_create_loadcollector(name="FORCE_LC")
hm_add_force(loadcollector="FORCE_LC", nodes=[<中心节点>], fz=-100)
hm_create_loadstep(name="static1", spc_loadcollector="SPC_LC", load_loadcollector="FORCE_LC")
hm_export(path=".../demo.fem", solver="optistruct")
```

全跑通后的 deck 体检报告应为：

```
GRID 441 / CQUAD4 400 / PSHELL 1 / MAT1 1 / SPC 126 / FORCE 1 / SUBCASE 1
spc_detail: {nodes: 21, fixed_dofs: 63}
case control: SUBCASE 1 · LABEL static1 · SPC = 1 · LOAD = 2
```

---

## 6. 能力边界（别承诺超出部分）

**能做**：平面/板件建模、曲面 2D 网格（尺寸精确）、实体抽中面（MidMesh）、
材料/属性/约束/载荷/工况、导出 OptiStruct / Nastran / Abaqus / Radioss / LS-DYNA deck、
任意 Tcl 逃生口（`hm_run_tcl`）。

**不能做**：
- 求解（只有前处理，OptiStruct 计算要另跑）
- 结果后处理（HyperView 未接）
- 读 CAD（STEP/IGES 导入未封装，但可用 `hm_run_tcl` 调 `*feinputwithdata2` 自己接）
- 3D 实体网格（tetramesh）
- BatchMesher（独立 Java 程序，CLI 可用但未封装成工具）

需要这些能力时，用 `hm_run_tcl` 写 Tcl 作为过渡，再决定是否固化成正式工具。
