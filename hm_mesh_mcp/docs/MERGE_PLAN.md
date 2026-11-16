# 与已有 HyperMesh MCP 的合并方案

本文针对一种真实场景：机器上**已经有一个自建的 HyperMesh MCP**（下文称 `hwmcp`），现在又要接入本仓库这套网格划分 MCP（下文称 `mesh-mcp`），需要决定「怎么并存、最终要不要合成一个」。

结论先给：**先并列（方案 A），把 `mesh-mcp` 的 Tcl 生成器逐步搬进 `hwmcp` 的常驻会话（方案 C）是终局；中间的「网关代理」（方案 B）在两边框架不一致时不划算，只在客户端只支持单连接时才值得做。**

---

## 1. 两套 MCP 的能力边界

| 能力 | `hwmcp`（已有） | `mesh-mcp`（本仓库） |
|---|---|---|
| 建基准面 / 曲面 2D 网格 | ✅ `hm_create_plane_surface`、`hm_mesh_surfaces` | ⚠️ 仅 `automesh_surfaces`（按已有曲面） |
| 实体自动网格（四面体/六面体） | ❌ | ✅ 探针分类 + drag/spin/tetra |
| 网格质量检查与修复 | ❌ | ✅ 含回退保护 |
| MAT1 / PSHELL / SPC / FORCE / SUBCASE | ✅ | ❌ |
| 导出 OptiStruct/Nastran/Abaqus/Radioss | ✅ `hm_export` | ❌ |
| 齿轮/剖切面等专用策略 | ❌ | ✅ |
| 中文质量与流程报告 | ❌ 仅 deck 体检 | ✅ |
| 任意 Tcl 执行 | ✅ `hm_run_tcl`（全开放） | ⚠️ 网格命令受白名单约束 |
| 工具数 | 20 | 33 |

交集只有「曲面网格」一项，其余**零重叠**。这是合并方案可以简单的前提。

---

## 2. 技术底座差异（决定了合并成本）

| 维度 | `hwmcp` | `mesh-mcp` |
|---|---|---|
| MCP 框架 | **手写 JSON-RPC 2.0**（零依赖，仅 stdlib） | **FastMCP**（`mcp==1.27.1`） |
| 执行器 | 常驻 GUI 会话：注入 `_sock.tcl`，TCP 一行进一行出 | 每次调用起一个 `hmbatch.exe` 进程；另可 attach 可见 GUI listener |
| 会话状态 | **有状态**（毫秒级往返，模型常驻内存） | **无状态**（每次 hmbatch 重新加载模型） |
| 传输格式 | 单行 Tcl（多行会被 `to_single_line()` 压平），返回单行 `OK:` / `ERR:` | 多行脚本写入临时文件，返回多行 stdout |
| 依赖 | 无 | `mcp<2` + pydantic 等约 30 个包 |
| License 模型 | 一次启动占用，后续调用不再消耗 | 每次调用消耗一次（进程级） |
| 端口 | 动态端口（`HWMCP_PORT` 可固定） | GUI listener 默认 `47881` |

**两条关键结论：**

1. `mesh-mcp` 的 `generate_*` 工具本质是**纯字符串生成器** —— 输入参数、输出 Tcl 文本，与执行层完全解耦。这使它成为「可复用零件」，可以塞进任何执行器。
2. `hwmcp` 的传输层是**单行协议**，而 `mesh-mcp` 生成的脚本包含 `proc` 定义、`foreach`、多行结构，且需要回收多行 `MCP_PROBE_SOLID` 结果。**这是深度合并唯一的真实技术障碍。**

---

## 3. 三个方案

### 方案 A：并列注册（当前状态，推荐立即采用）

两个独立进程、两个 MCP 连接器，工具名天然隔离（`hm_*` vs `*_tcl`）。

```json
{
  "mcpServers": {
    "hypermesh":      { "command": ".../hwmcp/.venv/python.exe", "args": [".../hwmcp/server.py"] },
    "hypermesh-mesh": { "command": ".../hm_mesh_mcp/.venv/Scripts/python.exe",
                        "args": [".../hm_mesh_mcp/hypermesh_mcp_server.py", "--transport", "stdio"] }
  }
}
```

**优点**：零改造、互不污染、可分别灰度与回滚。
**代价**：AI 需要自己判断该调哪个连接器；两套进程可能同时拉起 GUI（license 冲突）。

**必须约定的三条纪律：**

1. **license 互斥**：`hwmcp` 常驻 GUI 占一个 token，`mesh-mcp` 的 hmbatch 再占一个。若 license 池只有 1–2 个，禁止并发跑；建议在批量划分前先停 `hwmcp` 的 GUI 会话（`taskkill /F /IM hmopengl.exe`）。
2. **不要两边同时开 GUI**：`mesh-mcp` 的 GUI 模式（`start_hypermesh_gui_listener`）与 `hwmcp` 自动拉起的 `hmopengl.exe` 会争同一模型文件与同一份 license。约定：**实时交互走 `hwmcp`，批处理划分走 `mesh-mcp`，同一时刻只活一个**。
3. **产物目录分离**：`hwmcp` 输出到 `hwmcp/workspace/`，`mesh-mcp` 输出到 `hm_mesh_mcp/runs/`、`outputs/`，不要交叉写入。

---

### 方案 B：统一网关（不推荐，除非客户端只支持单连接）

用一个 FastMCP 主服务把两边挂进来。**但 `hwmcp` 是手写 JSON-RPC，不能直接 `mcp.mount()`**，所以只有两种实现：

| 实现 | 做法 | 工作量 | 风险 |
|---|---|---|---|
| B1 重写外壳 | 用 FastMCP 重写 `hwmcp` 的 20 个工具定义，内部仍调 `tools.py` | 中（约 200 行样板） | `tools.py` 逻辑不动，风险可控 |
| B2 stdio 代理 | 网关持有两个子进程（各跑原 server），按工具名前缀路由 JSON-RPC | 中高（要自己实现 MCP 客户端 + 生命周期管理） | 子进程崩溃检测、stdio 缓冲、超时传播都需自己兜 |

B2 的示意：

```
client ──stdio──> gateway ──stdio──> hwmcp/server.py        (hm_* 工具)
                       └────stdio──> hm_mesh_mcp/server.py  (mesh_* 工具)
```

**结论**：除非客户端确实不支持多 MCP 连接（WorkBuddy、Codex、Claude Desktop 都支持），否则这一步纯属增加故障面。**跳过。**

---

### 方案 C：深度合并（终局）

把 `mesh-mcp` 的生成器搬进 `hwmcp`，共用**一个常驻 GUI 会话**执行。

```
client ──stdio──> 合并后的单一 server
                     ├─ hm_*    （原有前处理链）
                     ├─ hm2d_*  （原 hwmcp 曲面/板壳）
                     └─ hm3d_*  （原 mesh-mcp 的探针/分类/tetra/drag/spin）
                          └── 统一执行器：常驻 socket 会话（一次启动，长期复用）
```

**收益**：license 只占一次；往返从「进程冷启动 15–20 秒」降到毫秒；模型状态在多个工具间连续（探针 → 分类 → 划分 → 质量检查可以针对同一个内存模型，不必反复读写 `.hm`）。
**成本**：必须改造 `hwmcp` 的传输层（见下）。

#### C-1 传输层改造（唯一的硬骨头）

现状：`hm_session.to_single_line()` 把多行 Tcl 压成一行，返回单行 `OK:` / `ERR:`。

`mesh-mcp` 的脚本需要三样东西：`proc` 定义、多行结构、多行结构化输出（`MCP_PROBE_BEGIN/SOLID/END`）。

建议做法（最小改动）：

1. **块传输**：把多行脚本 base64 编码后作为单行下发，在 Tcl 侧 `encoding convertfrom` 解码 → 写字临时 `.tcl` → `source`。这样单行协议不用改。
2. **多行回包**：约定 `RET_BEGIN` / `RET_END` 包裹，会话端按行累积直到 `RET_END`，再作为多行字符串返回。
3. **结果解析**：把 `mesh-mcp` 的 `_extract_probe_lines()` 与 `_parse_probe_facts()` 直接复用到 `hwmcp/tools.py`（纯 Python 函数，无依赖）。
4. **超时分级**：划分类调用放宽到 600 s（`mesh-mcp` 已有 `_estimate_tetra_timeout_seconds()` 可复用），几何类保持 60 s。

#### C-2 工具迁移映射

| `mesh-mcp` 原工具 | 合并后命名 | 备注 |
|---|---|---|
| `get_hypermesh_meshing_strategy` / `get_meshing_rules` / `get_cutsection_spin_workflow` | `hm3d_get_rules` | 三者可合并为一个带 `topic` 参数的工具 |
| `locate_hypermesh` / `check_hypermesh_connection` | **删除** | `hwmcp` 的 `hm_status` 已覆盖 |
| `create_gui_listener_tcl` / `start_hypermesh_gui_listener` / `execute_tcl_gui*` | **删除** | 常驻会话已内置 |
| `generate_geometry_probe_tcl` → `execute` | `hm3d_probe` | 生成+执行合并为一步 |
| `classify_all_solids_from_probe` | `hm3d_classify` | 纯计算，直接搬 |
| `generate_phase2_finalize_tcl` + 执行 | `hm3d_finalize_components` | 生成+执行合并 |
| `generate_plain_tetra_tcl` / `*_batched_*` | `hm3d_tetra` | `batched` 参数化 |
| `generate_guarded_drag_hex_tcl` / `*_batched_*` | `hm3d_drag_hex` | 同上 |
| `generate_cutsection_spin_hex_tcl` | `hm3d_spin_hex` | |
| `automesh_surfaces` / `automesh_surfaces_gui` | `hm_mesh_surfaces` 复用之 | 与 `hwmcp` 现有工具重合，取其一 |
| `write_*_report` | `hm3d_report` | |
| `execute_tcl` / `make_recorded_tcl_wrapper` | **删除** | 由 `hm_run_tcl` 承接 |

合并后工具总数约 **26 个**（20 + 33 − 重合与冗余），比现在两套加起来更少，AI 选择成本更低。

#### C-3 保留 `mesh-mcp` 独立运行的理由

即使做了 C，也建议**保留本仓库的独立形态**：

- `hmbatch` 批处理是**真正并行**的（多进程、无 GUI），适合几十个零件一次过夜跑；
- 独立 Tk 面板（`run_batch_meshing_panel.py`）可以完全脱离 AI 人工使用，是可交付给他人的工具；
- 出问题时能单独复现，不牵连主 MCP。

即：`mesh-mcp` 作为**批处理执行器 + 人工面板**长期保留，`hwmcp` 作为**交互式单一入口**。两者共享生成器代码（把 `generate_*` 抽成 `meshlib/` 纯函数包，两边 import）。

---

## 4. 冲突清单（做任何方案前先对齐）

| 冲突项 | 现状 | 处置 |
|---|---|---|
| MCP 连接器 key | 已有 `hypermesh` | 新增用 `hypermesh-mesh`，勿覆盖 |
| License 并发 | 两边各占 token | 约定互斥；或 license 池 ≥ 2 才并发 |
| GUI 进程 | `hwmcp` 自动拉 `hmopengl.exe` | `mesh-mcp` 只在批处理模式跑；GUI 模式串行 |
| 端口 | `hwmcp` 动态 / `mesh-mcp` 47881 | 不冲突，但固定 `HWMCP_PORT` 时避开 47881 |
| 环境变量 | `HWMCP_HM_EXE` vs `HYPERMESH_BATCH_EXE` / `HYPERMESH_GUI_EXE` | 语义不同（GUI vs 批处理），**不要互相赋值**：`hmbatch.exe` 在 `hwmcp` 下会 `Invalid input`（profile 不加载） |
| 产物目录 | `hwmcp/workspace/` vs `runs/`、`outputs/` | 不交叉 |
| Tcl 白名单 | `hwmcp` 全开放 / `mesh-mcp` 拦截原始网格命令 | 合并后统一走生成器，白名单作为兜底保留 |

> 特别注意第 5 条：`hwmcp` 必须用 `hmopengl.exe`（GUI 版），`mesh-mcp` 必须用 `hmbatch.exe`（批处理版）。两者**不能互换**，这是 2021.2 上已实测的硬约束。

---

## 5. 推荐路线与验收标准

| 阶段 | 动作 | 验收 |
|---|---|---|
| 阶段 0（已完成） | 本仓库封装、独立注册 `hypermesh-mesh` | `verify_env.py` 输出 33 tools + 路径正确 |
| 阶段 1 | 并列运行一周，只用批处理划分；记录两者同时活跃时的 license 冲突次数 | 无 OOM / 无 license 抢占失败 |
| 阶段 2 | 把 `generate_*` 与 `_parse_probe_facts` 抽成 `meshlib/` 纯函数包，两边共用 | 同一份输入，独立运行与合并运行产出 Tcl 字节级一致 |
| 阶段 3 | 改造 `hwmcp` 传输层（块传输 + 多行回包），接入 `hm3d_*` | 一次会话内完成「探针→分类→tetra→质量检查」全链，无进程重启 |
| 阶段 4 | 收敛工具表，删除冗余（§C-2 中标「删除」的项） | 工具数从 53 降到约 26，AI 选题准确率不下降 |

**不建议提前做的**：阶段 3 之前不要动 `hwmcp` 的传输层 —— 它是唯一在 2021.2 上验证过的常驻会话实现，改动风险高于收益。
