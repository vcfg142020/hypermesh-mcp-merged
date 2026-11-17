# AGENTS.md — 交给 AI 的部署指令

> **这份文件的读者是 AI 编程助手**（WorkBuddy / Claude Code / Cursor 等），不是人。
> 人类只需要把仓库地址丢给 AI 并说「按 AGENTS.md 部署」，其余由 AI 自行完成。
>
> 人类版的说明在 [`docs/DEPLOY.md`](docs/DEPLOY.md)，双机工作流在 [`docs/WORKFLOW.md`](docs/WORKFLOW.md)。

---

## 一、任务

在本机把 HyperMesh MCP 服务部署为客户端可用的 MCP server。完成后客户端能列出 **54 个工具**
（21 个 `hm_*` 交互工具 + 33 个批处理工具）。

成功标准（三条，缺一不可）：

1. `python deploy.py` 退出码为 `0`，输出「结论：部署完成」
2. 客户端 `mcp.json` 的 `mcpServers.hypermesh` 指向本仓库的 `hwmcp_merged/merged_server.py`
3. 部署完成后告知用户**重启客户端**（MCP 配置只在客户端启动时读取）

---

## 二、硬约束（违反即失败）

| 约束 | 原因 |
|---|---|
| **不要 `pip install` 任何东西** | 全仓库只用标准库；`mcp` 包由 `hwmcp_merged/mcp_shim.py` 在运行时注入假模块替代 |
| **不要手写 `mcp.json`** | 里面的解释器路径、仓库路径都是机器相关的，必须由 `deploy.py` 现算 |
| **不要修改仓库内任何 `.py` / `.tcl`** | 部署是纯配置行为，不需要改代码。改了会导致与上游分叉、无法 `git pull` |
| **不要改 `HWMCP_*` 以外的环境变量** | 尤其不要动 `HW_CONFIG_PATH`、`ALTAIR_LICENSE_PATH`、`SPLM_LICENSE_SERVER`|
| **不要把仓库放到含空格或中文的路径后手工修补** | 脚本支持这类路径；若真的出错，报错信息会指出具体位置，按提示处理 |
| **不要用 `hmbatch.exe` 顶替 `hmopengl.exe`** | 交互族需要 GUI 版才能拿到 `OptiStruct` profile |

---

## 三、执行

### 第 1 步：确认位置

```bash
cd <仓库根目录>          # 能看到 deploy.py、hwmcp/、hwmcp_merged/ 的那一层
python deploy.py --dry-run
```

`--dry-run` **不写任何文件**，只做探测。先看它报什么，再决定是否落盘。

### 第 2 步：正式部署

```bash
python deploy.py
```

如需锁定版本（机器上装了多个 HyperWorks）：

```bash
python deploy.py --version 2021.2
```

如需指定客户端（默认自动查找 WorkBuddy → Claude Desktop → Cursor）：

```bash
python deploy.py --client claude
python deploy.py --client "D:/some/other/mcp.json"
```

### 第 3 步：按输出判定

`deploy.py` 的输出里，`[OK ]` 是通过、`[..]` 是提示、`[!!]` 是阻塞项。**只要出现 `[!!]` 就是没装好**，
不要向用户报告成功。

要机器可读结果时：

```bash
python deploy.py --json
```

返回结构（关键字段）：

```json
{
  "ok": true,                    // ← 只看这个：true 才是装好了
  "steps": [{"check": "...", "ok": true, "detail": "..."}],
  "client": {"name": "WorkBuddy", "path": "C:/Users/.../mcp.json"},
  "written": true,
  "next": ["重启客户端 ...", "..."]
}
```

---

## 四、失败分支（按 `[!!]` 的那一项对症处理）

| 阻塞项 | 判定依据 | 处置 |
|---|---|---|
| `Python >= 3.9` | 版本号低于 3.9 | 换 3.9+ 的解释器重跑，或让用户安装。**不要试图改代码兼容 3.8** |
| `仓库文件完整` | 缺少具体文件名 | clone 不完整（或用了 zip 下载丢文件）。让用户重新 `git clone` |
| `HyperMesh hmopengl.exe` | 未找到 | 依次尝试：① `set HWMCP_HM_EXE=<安装根>\hwdesktop\hm\bin\win64\hmopengl.exe`；② `set HWMCP_HM_VERSION=2021.2`；③ `set ALTAIR_HOME=<安装根>`。安装目录名不含 `Altair` 时只能用 ①。可用 `python hwmcp/autodetect.py` 查看候选列表 |
| `hmbatch.exe（批处理族）` | 未找到 | 通常与上一条同因；确认安装根正确即可。批处理族不可用不影响交互族 |
| `服务静态自检` | 输出含 `[!!]` | 把那段输出原样贴给用户，不要自己猜。常见原因是 `_sock.tcl` 缺失或工具表构建失败 |
| `写入客户端配置` | JSON 解析失败等信息 | 目标文件不是合法 JSON。**不要覆盖它**，让用户确认后手工处理，或换 `--client <另一个路径>` |

补充：`HW_CONFIG_PATH` 被设置时，`--doctor` 会显示 `[..]`（非阻塞）。这是预期行为——批处理族调用时会
临时摘除该变量，因为指向自定义 GUI 配置会让 `hmbatch` 启动即报
`Invalid args to hm_framework (batch mode)`。**不要"修复"它。**

---

## 五、可选：真启动验证

静态自检不启动 HyperMesh。要确认真能跑，加 `--verify`（约 30-60 秒，**占 1 个 license 席位**）：

```bash
python deploy.py --verify
```

或在部署完成后单独跑：

```bash
python hwmcp/doctor.py
```

它会真启动 `hmopengl.exe`、注入 `_sock.tcl`、写一个模型再读回。看到 `profile = OptiStruct`
即证明交互族可用。**这一项失败不影响部署结论**（配置仍然是对的），但要如实告知用户
「配置已就绪，但 HyperMesh 启动验证未通过」。

---

## 六、交付话术

部署成功后，向用户报告这四件事，不要贴大段日志：

1. 工具数：54 个（21 交互 + 33 批处理）
2. 用的哪个 HyperWorks 版本与安装位置
3. 配置写到了哪个文件的哪个键（`mcpServers.hypermesh`）
4. **需要重启客户端**，连接器列表里若出现 `hypermesh` 需点「信任」

若用户是「回家继续用」场景，追加一句：`git pull` 后重跑 `python deploy.py` 即可，
配置无需手工改动（脚本幂等，不会重复备份）。

---

## 七、不要做的事（回顾，都是踩过的坑）

- **不要把 `mcp.json` 提交进仓库**——里面是机器相关路径。仓库只有 `mcp.json.example`。
- **不要提交 `out/`、`_sock.log`、`command*.tcl`**——运行产物，可能含客户模型内容。
- **不要在两处各放一份代码来回改**——客户端指向哪份就以那份为准，另一份只能从它同步过来。
- **不要在 `hwdesktop` 层找安装根**——安装根是 `hmopengl.exe` 往上四级
  （`<root>/hwdesktop/hm/bin/win64/hmopengl.exe`），`parents[4]`。
- **不要把 `hmbatch` 的退出码当成功标志**——它的退出码是脚本最后一条命令的返回值。
