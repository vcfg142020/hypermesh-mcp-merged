# HyperMesh MCP（合并版）

把两个独立的 HyperMesh MCP 服务合并成**一个进程、一套工具、一次配置**，共 **54 个工具**。

| 族 | 工具数 | 来源 | 执行通道 | 会话特性 |
|---|---|---|---|---|
| 交互族（`hm_*`） | 21 | [hwmcp](https://github.com/)（本仓库 `hwmcp/`） | 常驻 `hmopengl.exe` + 注入 `_sock.tcl` socket | **有状态**，模型常驻内存，毫秒级响应 |
| 批处理族 | 33 | `hm_mesh_mcp/`（`hypermesh-mcp` 的封装快照） | 每次拉起独立的 `hmbatch.exe` 进程 | **无状态**，一次调用一个进程 |

两族**业务代码均未改动**：上游 `hypermesh_mcp_server.py` 逐字节一致，`hwmcp` 原样 `import`。合并只发生在工具注册层。

## 为什么不用 `mcp.mount()`

两个上游用了**互不兼容的 MCP 框架**：

- `hwmcp`：手写 JSON-RPC 2.0 over stdio，工具表是 `[{name, description, inputSchema, impl}]`，`impl(session, args)`。
- `hm_mesh_mcp`：基于 **FastMCP**，工具用 `@mcp.tool()` 装饰，`impl(**kwargs)`。

`mcp.mount()` 要求双方都是同一个 MCP 实例。这里的做法是：

1. `mcp_shim.py` 往 `sys.modules` 注入一套**假的 `mcp` / `mcp.server.fastmcp`**，让 FastMCP 装饰器只负责"记录函数"，从而在上游零改动、且**不需要安装 `mcp` 包**的前提下加载它。
2. `schema.py` 用 `inspect.signature` + `typing.get_type_hints` 从函数签名反推 JSON Schema（含 `Optional[X]`、`list[int]`、`from __future__ import annotations` 的字符串注解），不引入 pydantic。
3. `merged_server.py` 汇总出统一的工具表，按 `kind` 分派：交互族 `impl(session, args)`，批处理族先 `accepts(fn, kwargs)` 校验参数再 `impl(**kwargs)`。

## 目录结构

```
.
├── hwmcp_merged/          # 合并层（本项目的主体）
│   ├── merged_server.py   # MCP 服务入口，54 个工具
│   ├── mcp_shim.py        # 假 mcp 模块注入，用于零改动加载 FastMCP 代码
│   ├── schema.py          # 由函数签名生成 JSON Schema + 参数校验
│   ├── verify_tools.py    # 四阶段逐工具验证（A 离线 / B 交互 / C 实体 / D 批处理）
│   ├── _mcpclient.py      # 极简 stdio MCP 客户端（供验证脚本用）
│   ├── make_report.py     # 把验证结果整理成报告
│   └── accept.py          # 按客户端配置原样启动的验收脚本
├── hwmcp/                 # 交互族：21 个 hm_* 工具，纯标准库
│   └── workspace/         # 验证用的两个模型（demo_plate.fem / e2e_plate.hm）
└── hm_mesh_mcp/           # 批处理族：33 个工具（已剔除 .venv / 缓存 / 产物）
```

`merged_server.py` 按 `__file__` 推导同级目录，**仓库根目录保持上述布局即可直接运行**，不需要装包、不需要设 `PYTHONPATH`。

## 配置客户端

```json
{
  "mcpServers": {
    "hypermesh": {
      "command": "C:/path/to/python.exe",
      "args": ["<repo>/hwmcp_merged/merged_server.py"],
      "env": {
        "HWMCP_AUTOSTART": "1",
        "HWMCP_HM_EXE": "F:/Program/Altair2021.2/hwdesktop/hm/bin/win64/hmopengl.exe"
      }
    }
  }
}
```

要点：

- `command` 必须是 **Python 绝对路径**。写 `"python"` 会命中 Windows 商店存根，直接报 `MCP error -32000`。
- `HWMCP_HM_EXE` 必须指向 **`hmopengl.exe`（GUI 版）**。用 `hmbatch.exe` 会导致 profile 不是 `OptiStruct`，材料/工况类命令全部失效。
- `HWMCP_AUTOSTART=1` 会在后台线程预热 HyperMesh，握手不受阻；首次 `hm_status` 需 15–25 秒属正常。
- 本机只应跑**一个** HyperMesh 实例：每个实例各借一个 license，且模型互不相通。

批处理族还需要告诉它 `hmbatch.exe` 在哪，二选一：

```bash
# 方式一：仓库内建文件（已 gitignore）
echo F:\Program\Altair2021.2\hwdesktop\hm\bin\win64\hmbatch.exe > hm_mesh_mcp/hypermesh_batch_path.txt

# 方式二：调用时显式传 hmbatch_path 参数
```

## 验收

```bash
# 三项硬指标
python hwmcp_merged/accept.py
#   a) initialize < 1s        b) tools/list = 54（含 21 个 hm_）   c) hm_status.profile = OptiStruct

# 逐工具验证（约 60 秒，会起 1 次 GUI + 若干次 hmbatch，各占一个 license）
python hwmcp_merged/verify_tools.py
python hwmcp_merged/make_report.py
```

`verify_tools.py` 分四个阶段，跨阶段各自重启会话：

| 阶段 | 内容 | license |
|---|---|---|
| A | 离线：纯生成器 / 纯规则 / 路径探测 / 白名单负向 | 不占 |
| B | 交互：常驻 GUI，跑完整板壳算例并导出 deck | 1 个 |
| C | 实体：造 `*solidblock` 后跑 MidMesh | 1 个 |
| D | 批处理：真起 `hmbatch` 做自动网格 | 每次 1 个 |

本机实测结果：**54 个工具 → 49 PASS / 0 FAIL / 5 N/A**，另有 9 条数值准确性断言全部通过。5 个 N/A 都是"可见 GUI listener"族，需要人先在 HyperMesh 里 `source` 监听脚本，自动跑会挂住。

准确性不是只看"没报错"，而是对照具体数字：

- 200×200 板 10 mm → 400 CQUAD4 / 441 GRID（= 20×20 / 21×21）
- 导出 deck 逐卡计数：GRID 441、CQUAD4 400、PSHELL 1、MAT1 1、SPC 126、FORCE 1、SUBCASE 1
- MidMesh → 400 个 2D + 80 个 1D 边单元
- `automesh_surfaces` 20 mm → 100 单元 / 121 节点（读产物文件复核）

## 已知坑

以下四条都是本机实测踩出来的，前两条已在包装层修掉。

### 1) `HW_CONFIG_PATH` 会让 `hmbatch` 启动即失败

若机器上设了指向自定义 GUI 配置的 `HW_CONFIG_PATH`（含 `views\mymodelview` 之类），`hmbatch` 启动时会执行 `hm_framework getpulldowns`（GUI 菜单动作），在 batch 模式下非法：

```
Tcl/Tk script error: Invalid args to hm_framework (batch mode).
    while executing "hm_framework getpulldowns"
HM exiting with code 1
```

脚本一行都没执行。**处理**：`_batch_call()` 在批处理调用期间临时摘掉该变量，结束复原；GUI 族仍保留它。

### 2) `hmbatch` 的退出码不等于成败

2021.2 实测：进程退出码**等于脚本最后一条命令的返回值**。

| 脚本 | 退出码 |
|---|---|
| `puts "x"` | 0 |
| `set n 1` | 1 |
| `set n 1` + `exit 0` | 1（显式 exit 也压不住） |
| `set n 1` + `set __mcp_rc 0` | 0 |

上游 `success = returncode == 0` 会把**已经跑完**的脚本误判为失败。**处理**：仅在「stdout 无 `Tcl/Tk script error` 且出现 `End of command file - terminating.`」时改判，并保留 `raw_returncode` + `success_note`，不隐藏原始信息。

### 3) `*solidblock` 是 12 个参数

```
*solidblock x0 y0 z0  Lx 0 0  0 Ly 0  0 0 Lz
```

只给 6 个数字虽然"成功"，但建出来是个歪块；且必须**当前 component 已存在**，否则返回 1 却一个 solid 都不建。

### 4) `generate_cutsection_spin_hex_tcl` 的 `spin_axis_point` 是运行期必填

该参数默认 `None`，也未列入 `inputSchema.required`，但不给会抛 `ValueError`。属上游签名缺陷，本仓库未改动上游代码，调用时请显式传入。

## 许可与来源

- 合并层（`hwmcp_merged/`）、`hwmcp/`：本仓库作者原创。
- `hm_mesh_mcp/`：来自第三方 `hypermesh-mcp` 项目的封装快照，**上游未声明 LICENSE**，按"保留所有权利"处理，仅作可复现的依赖快照保留，详见 `hm_mesh_mcp/NOTICE.md`。
- 本项目未使用 [CAE-Agent-Hub](https://github.com/Cai-aa/CAE-Agent-Hub) 的代码。其 HyperWorks MCP 依赖产品内扩展（`minProductVersion="2025"`）与 Python API（2022.1 起），在 2021.2 上不可用。
