# 变更记录

按时间倒序。版本号在 `0.x` 期间表示「接口可能变，但每次变更都已跑通全量验证」。

当前能力：**54 个工具 = 21 交互（`hm_*`）+ 33 批处理**，全量验证 65 PASS / 0 FAIL。

---

## [0.4.0] — 2026-11-17

**一键部署与 AI 可执行化。** 之前「能装」依赖人读文档；现在一条命令 + 一份 AI 契约。

### 新增

- **`deploy.py`** — 七步一键部署：Python 版本 → 仓库完整性 → 依赖 → HyperMesh 定位 →
  静态自检 → 写客户端配置 → （可选）真启动验证。
  - 幂等：配置已是最新时**跳过写入**，不产生重复 `.bak`（实测第二次运行零改动）
  - `--dry-run` 只看不写；`--json` 输出 `ok` 字段供 AI/CI 判定
  - `--client` 支持 `workbuddy` / `claude` / `cursor` / 任意 JSON 路径
  - 写配置前自动备份为 `.bak.YYYYmmdd-HHMMSS`
- **`AGENTS.md`** — 写给 AI 编程助手的部署契约：硬约束（不许 `pip install`、不许手写 `mcp.json`、
  不许改代码）、执行命令、成功判据、6 类失败分支的处置表、交付话术。
  人类只需说「按 AGENTS.md 部署」。
- **`docs/DEPLOY.md`** — 人读版部署手册：三个场景（新机器 / 回家更新 / 借来的机器）、
  七步逐条解释、参数速查、确认清单、7 条故障对照、回滚方式。
- **`CHANGELOG.md`** — 本文件。

### 修正

- `README.md` 目录结构里仍写着 `hwmcp/workspace/` 预置 `demo_plate.fem` / `e2e_plate.hm`。
  这两个模型早已移除（改为 `hwmcp_merged/fixtures.py` 运行时生成纯文本 deck），描述已更正。

---

## [0.3.0] — 2026-11-16

**文档补齐。** 无代码改动。

### 新增

- `docs/WORKFLOW.md` 第六节「同一台机器上别维护两份代码」。
  运行副本与仓库副本并存时，改了一处忘了另一处，症状是「我明明改了却没生效」。
  给出「一个事实来源，其余都是下游」的规则与 `cp` 同步片段，并推荐只留一份。
- 章节重编号至八节。

### 背景

这一节是被实际踩到才补的：客户端 `mcp.json` 指向工作区副本，`git push` 用仓库副本，
两者一度分叉 12 个文件。

---

## [0.2.1] — 2026-11-16

### 修正

- `--doctor` 的下一步提示用了相对路径，从仓库根执行时指向错误目录；改为绝对路径。
- `configure.py` / `make_report.py` / `doctor.py` 取安装根时用了 `parents[3]`，
  实际拿到的是 `hwdesktop` 而非安装根，导致配置降级为绝对路径、报告显示目录名错误。
  统一为 `parents[4]`（`<root>/hwdesktop/hm/bin/win64/hmopengl.exe`）。

---

## [0.2.0] — 2026-11-16

**可移植化。** 目标：`git clone` 到任意机器后不改代码、不改配置即可运行。

### 新增

- **`hwmcp/autodetect.py`** — 零依赖安装位置发现。优先级：
  `HWMCP_HM_EXE` → `ALTAIR_HOME` → Windows 卸载注册表 `InstallLocation` → 常见目录扫描 → `PATH`。
  多版本并存默认取最高版，用 `HWMCP_HM_VERSION` 锁定。支持 `--print <key>` 单值输出。
- **`configure.py`** — 一条命令生成客户端配置。优先写**版本号**（`HWMCP_HM_VERSION=2021.2`）
  而非绝对路径，使配置本身可跨机器复用。`--write` 自动备份后合并，`--json` 纯 JSON 输出。
- **`merged_server.py --doctor`** — 静态自检，<1 秒，输出中文宽度对齐的检查表。
- `mcp.json.example` — 占位符模板，指向生成器而非手工编辑。

### 修复

- **阶段 D 4 个工具 FAIL**（`FileNotFoundError: Could not find hmbatch.exe`）。
  上游 `_candidate_hmbatch_paths()` 只枚举 `Altair\2020` 固定路径。合并层改为用 `autodetect`
  结果注入 `HYPERMESH_BATCH_EXE` / `HYPERMESH_GUI_EXE`，**上游一行未改**。修复后 D 阶段 5/5 PASS。

### 变更

- `hwmcp/hm_session.py` 去掉写死的 exe，改为自动发现；找不到时给出三种可操作的处置方式，
  而不是抛裸 `FileNotFoundError`。
- 移除仓库内 3 个被透明加密破坏的预置模型（`.fem` / `.hm`），改为 `fixtures.py` 运行时生成
  最小 OptiStruct deck（4 GRID + 1 CQUAD4 + PSHELL + MAT1 + 2×SPC + FORCE）。
- `.gitignore` 修正：`_sock.tcl` 曾被误排除——它是注入 HyperMesh 的常驻 socket 服务源码，
  名称像运行产物但缺它交互族全废。

---

## [0.1.0] — 2026-11-16

**首个可用版本。** 把两个互不兼容的 HyperMesh MCP 合并为单进程。

### 新增

- **`hwmcp_merged/merged_server.py`** — 统一服务入口，54 个工具。
  按 `kind` 分派：交互族 `impl(session, args)`，批处理族先校验参数再 `impl(**kwargs)`。
- **`hwmcp_merged/mcp_shim.py`** — 向 `sys.modules` 注入假 `mcp` / `mcp.server.fastmcp`，
  使 FastMCP 写的上游代码在**零改动、且未安装 `mcp` 包**的前提下被加载。
- **`hwmcp_merged/schema.py`** — 由 `inspect.signature` + `typing.get_type_hints` 反推 JSON Schema
  （含 `Optional[X]`、`list[int]`、`from __future__ import annotations` 的字符串注解），不引入 pydantic。
- **`hwmcp_merged/verify_tools.py`** — 四阶段逐工具验证：
  A 离线 / B 交互 / C 实体 / D 批处理。
- `hwmcp_merged/accept.py`、`_mcpclient.py`、`make_report.py` — 验收与报告生成。

### 为什么不 `mcp.mount()`

两个上游框架不兼容：`hwmcp` 是手写 JSON-RPC（`impl(session, args)`），
`hm_mesh_mcp` 基于 FastMCP（`impl(**kwargs)`、`@mcp.tool()`）。`mount()` 要求同一个 MCP 实例。

---

## 已知限制

| 项 | 状态 |
|---|---|
| HyperWorks 2021.2 | 实测通过：`hmbatch` 与 GUI socket 双通道正常，`profile = OptiStruct`，启动 24.2 s |
| HyperWorks 2025 | 实测通过：双通道正常，`profile = OptiStruct`，启动 20.7 s |
| HyperWorks 2022.3 | **未做完整实测**。早期仅验证了启动通道可用（32.3 s），未跑逐工具验证 |
| 非 Windows 平台 | 不支持。`hmopengl.exe` / `hmbatch.exe` 无跨平台替代 |
| 并发 | 交互族串行（单 socket 会话）；批处理族每调用一个进程，天然并行但各占一个 license |

---

## 升级注意

- `0.1.x → 0.2.x`：若你手工写过 `mcp.json` 的绝对路径，重跑 `python deploy.py` 会覆盖成版本号写法。
  旧配置已被自动备份为 `.bak.*`。
- 任何版本升级后：`git pull` → `python deploy.py` → **重启客户端**。
