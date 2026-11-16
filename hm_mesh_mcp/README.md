# HyperMesh Meshing MCP（封装版）

把 Altair HyperMesh 的**实体网格自动划分**流程封装成 33 个 MCP 工具：AI 可以驱动它跑完整条流水线，也可以完全脱离 AI，用自带的 Windows 图形面板手动跑。

本仓库是一个**可直接运行的封装发行版**，不是原项目源码的简单镜像 —— 增加了 venv 依赖锁定、启动器、自检脚本、WorkBuddy/Codex 配置片段，以及一份「与已有 HyperMesh MCP 合并」的方案文档。

---

## 1. 它解决什么问题

**只做一件事：实体网格划分的策略决策与执行。**

```
探几何 → 按几何事实分类 → 匹配网格策略 → 分批执行 → 质量校验与回退 → 中文报告
```

| 做什么 | 不做什么 |
|---|---|
| 粗网格探针识别每个实体的几何特征 | 读 STEP/IGES/Parasolid 之外的 CAD 清理 |
| 自动判 `drag_hex` / `spin_hex` / `tetra` | 建立装配连接（RBE2/RBE3/焊缝/点焊） |
| 受控拖拽六面体、剖切面旋转六面体 | 材料/属性/载荷/工况设置 |
| 曲面偏差 R-trias 四面体 + 2D 先修后划 | 求解器 deck 导出 |
| 质量检查、受控修复、失败回退 | 结果后处理（HyperView/HyperGraph） |
| 组件改名与着色、齿轮齿形识别 | 模型文件加密/解密 |

> 如果你的需求是「板壳算例 → MAT1/PSHELL → SPC/FORCE → 导 OptiStruct deck」，这不是本项目的适用范围，见 [docs/MERGE_PLAN.md](docs/MERGE_PLAN.md) 中与另一套 MCP 的分工。

---

## 2. 实测基线

本封装在下列组合上验证到「服务可启动、33 个工具全部注册、HyperMesh 路径正确解析」：

| 项 | 版本 |
|---|---|
| 操作系统 | Windows（`win32`） |
| HyperMesh | Altair HyperWorks **2021.2**（`F:\Program\Altair2021.2`） |
| Python | 3.13.12（venv） |
| MCP SDK | `mcp==1.27.1`（**必须 < 2**，见 §7） |
| 工具数 | 33 |

自检命令：

```bat
.venv\Scripts\python.exe verify_env.py
```

预期输出 `tool count : 33` 与 `selected` 指向你的 `hmbatch.exe`。

`verify_env.py --full` 会额外跑一次真实 hmbatch 连通性探测 —— **会短暂占用一个 license**，未确认前请勿在共享 license 服务器上随意连跑。

---

## 3. 目录结构

```
.
├─ hypermesh_mcp_server.py        # MCP 主服务（33 个工具，FastMCP）
├─ start_mcp.bat                  # stdio 启动器（可直接作为 MCP command）
├─ verify_env.py                  # 环境自检（默认只读，--full 才起 hmbatch）
├─ mcp_config.workbuddy.json      # 现成的 MCP 注册片段
├─ requirements.txt               # 上游原始依赖（仅 mcp）
├─ requirements.lock.txt          # 本封装实测通过的完整依赖锁
├─ hypermesh_batch_path.txt       # 本机 hmbatch 路径（不入库，用 .example 模板）
├─ launch_meshing_workflow_panel.tcl   # HyperMesh 内 GUI 面板（人工入口）
├─ run_batch_meshing_panel.py     # 独立 Tk 后台划分面板（脱 AI 使用）
├─ run_full_meshing_workflow.py   # 离线全流程脚本
├─ parallel_hm_ansa.py            # HyperMesh + ANSA 并行桥
├─ docs/
│  ├─ AGENT_CONTRACT.md           # 上游 agent 操作契约（工具调用规则，权威）
│  ├─ MERGE_PLAN.md               # 与已有 HyperMesh MCP 的合并方案
│  └─ SETUP_WINDOWS.md            # Windows 从零部署与排错
├─ 01_后台划分_双击入口/           # 日常人工使用入口（双击 .vbs）
├─ 02_迁移到其他电脑_双击配置/      # 移植到别的机器
├─ 03_MCP服务入口_一般不用/        # 服务启停脚本
└─ 04_文档说明/                    # 上游流程 SOP 与工作流逻辑
```

---

## 4. 安装

### 4.1 复用已就绪的 venv（本机最快）

本目录下的 `.venv` 已经是可用状态，直接：

```bat
.venv\Scripts\python.exe verify_env.py
```

### 4.2 从零安装（联网）

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.lock.txt
```

若只用最小依赖，`pip install "mcp==1.27.1"` 亦可，但**务必锁 `<2`**。

### 4.3 无网机器

上游在原仓库 `wheels/` 里准备了离线 wheel 包，但**全部是 CPython 3.12 专用**（`pydantic_core`、`cffi`、`pywin32` 均为 `cp312-win_amd64`）。

因此离线部署的唯一正确姿势是：目标机安装 **Python 3.12 64 位**，然后

```bat
python -m pip install --no-index --find-links wheels -r requirements.txt
```

在 3.13 上会直接报 `No matching distribution`。本仓库未携带 `wheels/`（体积 35 MB 且仅对 3.12 有效），需要时从上游取。

### 4.4 配置 HyperMesh 路径

优先级由高到低：

1. 环境变量 `HYPERMESH_BATCH_EXE` / `HYPERMESH_GUI_EXE`
2. 项目根目录 `hypermesh_batch_path.txt` 的第一行非空内容
3. 内置候选列表（硬编码 `Altair\2020` 系列路径）

把 `hypermesh_batch_path.example.txt` 复制为 `hypermesh_batch_path.txt` 并改成你的实际路径即可。该文件已加入 `.gitignore`，避免把个人安装路径推到公开仓库。

---

## 5. 接入 WorkBuddy / Codex

把 `mcp_config.workbuddy.json` 的内容合并进 `~/.workbuddy/mcp.json`（注意是 `mcp.json`，不是 `.mcp.json`）：

```json
{
  "mcpServers": {
    "hypermesh-mesh": {
      "command": "<仓库路径>/.venv/Scripts/python.exe",
      "args": ["<仓库路径>/hypermesh_mcp_server.py", "--transport", "stdio"],
      "env": {
        "HYPERMESH_BATCH_EXE": "<你的 hmbatch.exe>",
        "HYPERMESH_GUI_EXE": "<你的 hw.exe>",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

保存后需在连接器管理页右上角「自定义连接器」里对该条目点**信任**，服务才会拉起。

> 已存在同名 `hypermesh` 连接器时不要覆盖 —— 用不同 key（如 `hypermesh-mesh`）并列注册，两者互不影响，合并策略见 [docs/MERGE_PLAN.md](docs/MERGE_PLAN.md)。

SSE 模式（供支持 HTTP 的客户端）：

```bat
.venv\Scripts\python.exe hypermesh_mcp_server.py --transport sse --port 8742
```

---

## 6. 工具清单（33 个）

**知识/规则（只读，建议先读）**

| 工具 | 作用 |
|---|---|
| `get_hypermesh_meshing_strategy` | 返回整体划分策略与参数基线 |
| `get_meshing_rules` | 结构化 tetra / drag / spin 规则 |
| `get_cutsection_spin_workflow` | 剖切面旋转的完整工作流说明 |

**定位与连接**

| 工具 | 作用 |
|---|---|
| `locate_hypermesh` | 枚举可用 hmbatch / GUI 可执行文件 |
| `check_hypermesh_connection` | 起一次 hmbatch 验证连通（占 license） |
| `create_gui_listener_tcl` | 生成 GUI 监听 Tcl（需在 HyperMesh 里 source） |
| `start_hypermesh_gui_listener` | 尝试拉起带监听的可见 GUI |
| `execute_tcl_gui` / `execute_tcl_gui_async` | 在可见会话中执行 Tcl（同步/异步） |
| `get_gui_async_job_status` | 查询异步 GUI 任务状态 |

**执行**

| 工具 | 作用 |
|---|---|
| `execute_tcl` | 批处理模式执行 Tcl（受网格命令白名单约束） |
| `make_recorded_tcl_wrapper` | 把录制的 Tcl 包成带签名标记的脚本 |

**几何探针与分类**

| 工具 | 作用 |
|---|---|
| `generate_geometry_probe_tcl` | 生成临时粗网格探针脚本 |
| `run_geometry_probe_gui` | 在 GUI 中跑探针，返回 `MCP_PROBE_SOLID` 行 |
| `classify_all_solids_from_probe` | 按几何事实分类（gear_aware_tetra / drag_hex / spin_hex / tetra_plain） |
| `recommend_tetra_sizes_from_probe_lines` | 由探针结果推每实体四面体尺寸 |

**命名与着色（Phase 2，强制）**

| 工具 | 作用 |
|---|---|
| `suggest_component_names` | 建议组件名 |
| `generate_rename_components_tcl` / `generate_component_colors_tcl` | 改名 / 着色 Tcl |
| `generate_finalize_components_tcl` | 合并的 finalize 脚本 |
| `generate_phase2_finalize_tcl` | 由分类结果生成 Phase 2 脚本（必须执行，否则后续网格被拦） |

**网格生成**

| 工具 | 作用 |
|---|---|
| `generate_surface_automesh_tcl` | 简单曲面自动网格 |
| `generate_plain_tetra_tcl` / `generate_batched_plain_tetra_tcl` | 曲面偏差 R-trias 四面体（单个/批量） |
| `generate_guarded_drag_hex_tcl` / `generate_batched_drag_hex_tcl` | 受控拖拽六面体（单个/批量） |
| `generate_cutsection_spin_hex_tcl` | 剖切面旋转六面体 |
| `automesh_surfaces` / `automesh_surfaces_gui` | 直接曲面划分（批处理/GUI） |

**齿轮与报告**

| 工具 | 作用 |
|---|---|
| `generate_gear_tooth_preview_tcl` / `generate_delete_gear_tooth_preview_tcl` | 齿形预览与清理 |
| `write_gear_tooth_recognition_report` | 齿形识别诊断报告 |
| `write_chinese_meshing_workflow_report` | 中文流程报告 |

完整调用规则（哪些命令被拦截、标记格式、回退条件）以 [docs/AGENT_CONTRACT.md](docs/AGENT_CONTRACT.md) 为权威。

---

## 7. 六个会咬人的坑（都实测过）

1. **`mcp` 必须 `< 2`。** pip 默认装 2.3.0，会抛 `ModuleNotFoundError: mcp.server.fastmcp`（FastMCP 在 2.x 更名为 `MCPServer`）。必须锁 `mcp==1.27.1`。
2. **离线 wheels 只认 Python 3.12。** 3.13 上 `--no-index` 必然失败。
3. **原始网格命令被白名单拦截。** `*meshdragelements2`、`*tetmesh`、`*meshspinelements` 等无法从 `execute_tcl` 直接下发，必须用 `generate_*` 生成器，且脚本中 `MCP_SCRIPT_BEGIN` / `MCP_SCRIPT_END` 标记完整。
4. **Phase 2 未完成会阻断后续。** 分类后必须先跑到 `MCP_FINALIZE_OK`，否则生成类网格脚本被拒。
5. **GUI 模式要手工 source listener Tcl。** 默认端口 `47881`，被占用时需在生成与执行两侧同时改端口。
6. **每次 `execute_tcl` 都会起一个 hmbatch 进程。** 大批量划分请用 `*_batched_*` 生成器，把多个实体塞进一个脚本，避免反复占 license。

---

## 8. 与已有 MCP 的关系

本 MCP 与「板壳前处理 / deck 导出」型 MCP 是**能力互补、不重叠**的两套东西。合并（并存、网关、深度整合）三种路径的取舍、冲突清单与迁移步骤，见 [docs/MERGE_PLAN.md](docs/MERGE_PLAN.md)。

---

## 9. 已知限制

- **无 CAD 导入与几何清理**：输入假定已经是干净的实体。
- **spin_hex 依赖真实剖切面**：无法生成有效剖切面或不出六面体时，自动回落 tetra。
- **单次调用上限**：单次建模/划分的实体规模受脚本超时约束，超大模型需按实体分批。
- **无结果后处理**：不读 `.h3d` / `.op2`，不出云图与曲线。
- **命名依赖组件名**：Phase 2 的改名/着色是后续可读性的前提，跳过会显著降低可维护性。

---

## 10. 来源、改动与许可

- **上游**：[`times1234/hypermesh-mcp`](https://github.com/times1234/hypermesh-mcp)（单次提交，版本标注 5.0「新增联动ansa」）。
- **本封装新增**：`.venv` 依赖锁定与 `requirements.lock.txt`、`start_mcp.bat`、`verify_env.py`、`mcp_config.workbuddy.json`、`docs/MERGE_PLAN.md`、`docs/SETUP_WINDOWS.md`、`.gitignore` 扩充、`README.md` 重写（上游原始 README 保留为 `docs/AGENT_CONTRACT.md`，内容未改）。
- **本封装未改动**：`hypermesh_mcp_server.py` 及全部业务脚本逻辑，与上游一致。
- **许可状态**：上游仓库**未提供 LICENSE 文件**，按默认版权规则属「保留所有权利」。因此本仓库定位为个人/团队内部可用的封装发行版，**不主张对上游代码的再授权**。如需对外分发或商用，请先联系上游作者取得许可。详见 [NOTICE.md](NOTICE.md)。

---

## 11. 故障排查

| 现象 | 原因与处置 |
|---|---|
| `ModuleNotFoundError: mcp.server.fastmcp` | 装了 mcp 2.x，降级到 `mcp==1.27.1` |
| `No matching distribution found for mcp` | 镜像/网络问题，换源重试；或按 §4.3 用 3.12 离线装 |
| `Could not find hmbatch.exe` | 设 `HYPERMESH_BATCH_EXE` 或改 `hypermesh_batch_path.txt` |
| 网格脚本被拒（含 `*tetmesh` 等） | 用了原始 Tcl，改走 `generate_*` 生成器 |
| 分类后生成脚本仍被拒 | Phase 2 未完成，先跑 `generate_phase2_finalize_tcl` |
| GUI 执行超时/无响应 | listener 未 source、端口冲突、或 HyperMesh 未打开模型 |
| hmbatch 报 license 不足 | 并发过高，改用 `*_batched_*` 减少进程数 |
