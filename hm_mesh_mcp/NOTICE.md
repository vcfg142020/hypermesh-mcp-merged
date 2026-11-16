# 来源与归属声明

## 上游项目

本仓库的 `hypermesh_mcp_server.py`、`parallel_hm_ansa.py`、`run_batch_meshing_panel.py`、
`run_full_meshing_workflow*.py`、`launch_meshing_workflow_panel.tcl`、`ANSA Auto Mesh BRIDGE.ps1`
以及 `01_` ~ `04_` 各目录下的脚本与文档，均来自：

- **仓库**：https://github.com/times1234/hypermesh-mcp
- **抓取提交**：`886655f`（提交说明「5.0（新增联动ansa）」）

原项目的 `README.md` 被完整保留为 [`docs/AGENT_CONTRACT.md`](docs/AGENT_CONTRACT.md)，内容未作修改。
它记录的工具调用契约（网格命令白名单、`MCP_SCRIPT_BEGIN/END` 标记、Phase 2 完成条件）是本项目的行为规范，
修改脚本前应先读它。

## 许可证状态（重要）

**上游仓库未提供 LICENSE 文件。** 按伯尔尼公约与 GitHub 服务条款，无许可证的公开仓库默认适用
「保留所有权利」（All rights reserved）—— 公开可见不等于可自由使用、修改、再分发。

因此：

1. 本仓库**不主张**对上游代码的著作权，也**不提供**任何再授权（不附加 MIT/Apache 等条款）。
2. 就上游代码而言，本仓库的定位是**个人/团队内部的部署封装与运维文档**，用于本机使用与内部技术改造。
3. 如需对外分发、集成进商业产品、或提交到公司代码库，**请先联系上游作者取得书面许可**。
4. 若你在自己的账号下公开此仓库，建议保留本文件、保留上游链接，并在仓库描述中注明「基于 times1234/hypermesh-mcp 的封装」。

删除或隐藏本文件、把上游代码重命名为自有项目对外发布，均不在本封装的建议做法之内。

## 本封装新增的内容

以下为本封装相对上游的新增或修改，可按需独立评估：

| 文件 | 性质 |
|---|---|
| `README.md` | 重写（上游 README 移至 `docs/AGENT_CONTRACT.md`） |
| `docs/MERGE_PLAN.md` | 新增：与另一套 HyperMesh MCP 的合并方案 |
| `docs/SETUP_WINDOWS.md` | 新增：部署清单与排错 |
| `NOTICE.md` | 新增：本文件 |
| `start_mcp.bat` | 新增：stdio 启动器 |
| `verify_env.py` | 新增：环境自检 |
| `mcp_config.workbuddy.json` | 新增：注册片段 |
| `requirements.lock.txt` | 新增：实测通过的依赖锁 |
| `hypermesh_batch_path.example.txt` | 新增：路径模板 |
| `.gitignore` | 扩充（忽略 `.venv`、`wheels`、本机路径文件等） |

**业务逻辑零改动**：`hypermesh_mcp_server.py` 与上游逐字节一致，未插入任何工具、未修改任何生成器。

## 第三方依赖

运行时依赖见 `requirements.lock.txt`，均为 PyPI 上的公开包（`mcp`、`pydantic`、`starlette`、`httpx` 等），
各自适用其上游许可证，以各包随附的 LICENSE 为准。

`mcp` 必须锁 `<2`：2.x 将 `mcp.server.fastmcp` 更名为 `mcp.server.mcpserver`，本服务基于 1.x API 编写。

## 商标

Altair、HyperMesh、HyperView、HyperStudy、OptiStruct、Radioss、ANSA 为其各自权利人的商标或注册商标。
本项目与 Altair Engineering Inc.、BETA CAE Systems 均无隶属关系，未获其背书。
