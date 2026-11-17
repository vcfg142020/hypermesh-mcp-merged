# 部署说明

三条命令之内能装完，并且**换一台机器不需要改任何代码**。

- 想让人读的完整流程 → 本文
- 想让 AI 自己动手 → 把仓库丢给它，说「按 [AGENTS.md](../AGENTS.md) 部署」
- 双机（公司↔家）日常循环 → [WORKFLOW.md](WORKFLOW.md)

---

## 一、前置条件

| 项 | 要求 | 怎么确认 |
|---|---|---|
| 操作系统 | Windows（`hmopengl.exe` / `hmbatch.exe` 决定，无跨平台方案） | — |
| HyperWorks | 2021.2 及以上，**已能正常启动** | 手工双击 HyperMesh 能开即可 |
| Python | 3.9+ | `python -V` |
| 网络 | 仅 `git clone` 时需要；之后完全离线可用 | — |
| 依赖包 | **不需要**。零第三方依赖，无需 `pip install` | — |

许可（license）不归本仓库管：沿用你机器上 HyperMesh 的既有配置。若 HyperMesh 本身能启动，MCP 就能用。

---

## 二、场景 A：新机器首次部署

```bash
git clone https://github.com/vcfg142020/hypermesh-mcp-merged.git
cd hypermesh-mcp-merged
python deploy.py
```

看到这一幕就完成了：

```
==========================================================================
结论：部署完成。
  1. 重启客户端（WorkBuddy / Claude Desktop），让新的 mcp.json 生效
  2. 连接器列表里若出现 hypermesh，点击信任
  3. 可选：python hwmcp/doctor.py  真启动一次确认（30-60 秒）
==========================================================================
```

然后**重启客户端**——MCP 配置只在客户端启动时读取，不重启看不到新工具。

### 装之前想先看一眼？

```bash
python deploy.py --dry-run
```

只探测、不写文件。适合先确认它认得的 HyperWorks 版本对不对。

### 机器上有多个 HyperWorks

`deploy.py` 默认取**最高版本**。要指定：

```bash
python deploy.py --version 2021.2
```

写进配置的是 `HWMCP_HM_VERSION=2021.2` 这种**版本号**，不是绝对路径，所以这份配置本身可以搬到别的机器用。

---

## 三、场景 B：回家继续用

```bash
cd hypermesh-mcp-merged
git pull
python deploy.py
```

**配置通常不需要重做。** 脚本会先比对：如果现有配置已经是最新形态，直接跳过写入，
不会产生 `.bak` 文件。家里 HyperWorks 版本不同也没关系——`autodetect` 会自己找到，
或者脚本会提示你加 `--version`。

只有这几种情况才会真的改写配置：

- 首次部署
- 换了 HyperWorks 版本（旧配置仍指向已卸载的版本）
- 仓库换了位置（`args` 里的路径失效）

---

## 四、场景 C：借来的机器 / 临时环境

不想留痕迹时，配置写到临时位置，不动用户目录：

```bash
python deploy.py --client ./mcp.tmp.json
```

用完删掉该文件即可。客户端若要临时用，把这份 JSON 的内容贴进它的配置即可。

---

## 五、`deploy.py` 到底做了什么

七步，任何一步失败都会明确告诉你缺什么：

| # | 步骤 | 检查内容 |
|---|---|---|
| 1 | Python 版本 | ≥ 3.9 |
| 2 | 仓库完整性 | 8 个关键文件在位（`_sock.tcl`、`mcp_shim.py`、上游 server 等） |
| 3 | 第三方依赖 | 恒为通过——真的一个都不需要 |
| 4 | HyperMesh 定位 | 环境变量 → 注册表 → 目录扫描 → `PATH`，多版本取最高 |
| 5 | 静态自检 | 跑 `merged_server.py --doctor`，构建工具表（应 54 个） |
| 6 | 写客户端配置 | 自动备份原文件（`.bak.YYYYmmdd-HHMMSS`），合并进 `mcpServers.hypermesh` |
| 7 | 真启动验证 | **仅 `--verify` 时执行**，约 30-60 秒 |

第 4 步的查找顺序：`HWMCP_HM_EXE` → `ALTAIR_HOME` → Windows 卸载注册表 `InstallLocation`
→ 常见目录扫描 → `PATH`。安装根按 `hmopengl.exe` 往上四级推算
（`<root>/hwdesktop/hm/bin/win64/hmopengl.exe`）。

### 参数速查

| 参数 | 作用 |
|---|---|
| `--dry-run` | 只探测，不写任何文件 |
| `--version 2021.2` | 锁定 HyperWorks 版本 |
| `--client claude` | 目标客户端：`workbuddy` / `claude` / `cursor` / 任意 JSON 路径 |
| `--verify` | 额外真启动一次 HyperMesh（占 1 个 license） |
| `--json` | 输出机器可读结果，供 AI / CI 判定 |

`--json` 的 `ok` 字段是唯一权威判据；`[!!]` 在人类输出里对应它下面的 `steps[].ok == false`。

---

## 六、部署后的确认清单

- [ ] `deploy.py` 退出码为 0，输出「结论：部署完成」
- [ ] 客户端重启后，工具列表出现 **54 个**工具（其中 21 个以 `hm_` 开头）
- [ ] 连接器列表里 `hypermesh` 已信任
- [ ] （可选）`python hwmcp/doctor.py` 打印 `profile = OptiStruct`

强制核对三项硬指标（会真启动一次，约 30-60 秒）：

```bash
cd hwmcp_merged && python accept.py
```

期望输出：

```
a) initialize < 1000 ms  -> OK
b) tools/list 54 个（hm_ 开头 21 个）
c) hm_status profile = OptiStruct  -> OK
```

---

## 七、故障对照

| 现象 | 原因 | 处置 |
|---|---|---|
| `未定位到 HyperMesh` | 安装目录名不含 `Altair`，或装在非常规路径 | `set HWMCP_HM_EXE=<安装根>\hwdesktop\hm\bin\win64\hmopengl.exe` |
| 客户端看不到任何工具 | 改配置后没重启客户端 | 完全退出客户端再启动（不是关窗口） |
| 工具列表有 54 个但调用报错 | `_sock.tcl` 未注入成功 | `python hwmcp/doctor.py` 看具体环节 |
| `hmbatch` 一启动就报 `Invalid args to hm_framework (batch mode)` | `HW_CONFIG_PATH` 指向了自定义 GUI 配置 | 不要手工删该变量；批处理族调用时脚本会自动临时摘除 |
| 中文路径下报 `SyntaxError: invalid non-printable character U+FEFF` | 文件带 UTF-8 BOM | 用 `encoding="utf-8-sig"` 读，或去掉 BOM |
| 改了一行代码但不生效 | 客户端指向的是另一个副本 | 查 `mcp.json` 的 `args` 指向哪；见 WORKFLOW 第六节 |
| 部署后 `git status` 一堆 `Bin` 变更 | 磁盘文件被透明加密（DLP）而 `git.exe` 不在白名单 | 用仓库里的明文暂存通道提交，不要 `git add` |

---

## 八、回滚 / 卸载

部署只改了一个文件：客户端的 `mcp.json`，且写之前自动备份。

```bash
# 恢复上一次配置
copy "C:\Users\<你>\.workbuddy\mcp.json.bak.20261116-180527" "C:\Users\<你>\.workbuddy\mcp.json"
```

或手工编辑 `mcp.json`，删掉 `mcpServers.hypermesh` 整个键即可。仓库目录直接删掉，无残留、无注册表写入、
不装任何系统服务。

---

## 九、让 AI 替你装

把仓库地址和这一句话丢给任意 AI 编程助手：

> 把这个仓库部署到本机，按仓库里的 AGENTS.md 执行。

AI 会读到 [`AGENTS.md`](../AGENTS.md)，里面有执行命令、成功判据（`--json` 的 `ok` 字段）
和 6 类失败分支的处置方式。它不需要问你 HyperMesh 装在哪——`autodetect` 会算。

**不想自己组织语言？** [`docs/PROMPT.md`](PROMPT.md) 里有 5 段可直接复制的完整指令
（标准部署 / 回家更新 / 只诊断 / 多版本锁定 / 非 WorkBuddy 客户端），
另附一张「AI 跑偏了怎么纠」的对照表。

你只需要在它做完后**重启客户端**，这一步 AI 代替不了。
