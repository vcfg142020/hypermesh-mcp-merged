# 可直接粘贴的部署指令

给 AI 编程助手用。**选一个场景，复制整个代码块，改掉两个尖括号占位符**，发给 AI 即可。

粘之前只需要改两处：

- `<repo-url>` → 仓库地址，如 `https://github.com/vcfg142020/hypermesh-mcp-merged.git`
- `<目录>` → 你希望克隆到哪，如 `D:/code/hypermesh-mcp`（不确定就删掉那一行，让 AI 自己选）

---

## 场景 1：标准部署（新机器，最常用）

```
把这个仓库部署到本机：<repo-url>
克隆到 <目录>（若该目录已有仓库则先 git pull）

严格按仓库根目录的 AGENTS.md 执行，不要凭猜测。

执行顺序：
1. 先跑 python deploy.py --dry-run，把出现的 [!!] 项原样报给我，等我确认再继续
2. 我确认后跑 python deploy.py --json，只以返回的 ok 字段为 true 作为成功判据
3. 如果 ok 为 false，按 AGENTS.md 第四节的分支表处置；处置不了就把报错原文贴给我

硬性禁止：pip install 任何包、手工写 mcp.json、修改仓库里的 .py / .tcl 文件。

完成后只汇报四件事：工具数量、实际使用的 HyperWorks 版本与安装位置、
配置写入的文件与键名、我需要手动做什么（例如重启客户端）。
```

适用：第一次在任意机器上装。

---

## 场景 2：回家更新（仓库已在，配置也在）

```
在 <目录> 更新并重新部署 HyperMesh MCP。

1. git pull
2. python deploy.py --json
3. 如果 written 为 false，说明配置没变，告诉我"无需重新配置"就结束
4. 如果 written 为 true，说明配置被改写了，把改动原因（版本变化 / 仓库换位置 / 首次）
   从 notes 里读出来告我

完成后提醒我：是否需要重启客户端。
不要重复运行造成多个 .bak；deploy.py 本身幂等，重复跑是安全的。
```

适用：每天回家。通常 `written` 会是 `false`，一句话就结束。

---

## 场景 3：只诊断，不改动

```
先别动任何东西，只诊断这台机器能不能跑 HyperMesh MCP。

仓库在 <目录>。执行：
    python deploy.py --dry-run --json

把每一步的 ok 与 detail 列成表格给我，重点是：
- 找到了哪个 HyperWorks 版本、在哪个路径
- 有没有多个版本并存
- 服务静态自检是否通过（工具表应为 54 个）

不要写任何文件，不要改环境变量。等我决定下一步。
```

适用：换新机器先探路、或部署失败后定位。`--dry-run` 保证零副作用。

---

## 场景 4：多版本锁定

```
在 <目录> 部署 HyperMesh MCP，并且锁定 HyperWorks 2021.2。

    git pull
    python deploy.py --version 2021.2 --json

注意：写进配置的应当是 HWMCP_HM_VERSION=2021.2 这种版本号，不是绝对路径。
如果机器上找不到 2021.2，不要自动降级到别的版本，停下来告诉我实际有哪些版本。
```

适用：机器上装了多个 HyperWorks，不想用默认的最高版本。把 `2021.2` 换成你要的版本。

---

## 场景 5：装到非 WorkBuddy 客户端

```
在 <目录> 部署 HyperMesh MCP 到 Claude Desktop（不是 WorkBuddy）。

    python deploy.py --client claude --json

如果返回的 client.path 不是你期望的位置，停下来告诉我它找到了什么，不要自己另选路径。
完成后告诉我该重启哪个程序。
```

`--client` 可选值：`workbuddy` / `claude` / `cursor` / 任意 JSON 路径。
Claude Desktop 与 Cursor 的配置结构相同，都是 `mcpServers` 键。

---

## AI 跑偏了怎么纠

| 它做了什么 | 你怎么说 |
|---|---|
| 开始 `pip install` | 「停下。这个项目零第三方依赖，`mcp` 包由 `mcp_shim.py` 运行时注入。按 AGENTS.md 重来。」 |
| 手工编辑 `mcp.json` 写了绝对路径 | 「删掉你写的内容，恢复 `.bak.*` 备份，只跑 `python deploy.py`。」 |
| 改了仓库里的 `.py` 让代码"适配"本机 | 「`git checkout -- .` 还原。部署是配置行为，不需要改代码。」 |
| 报"部署成功"但你没看到 54 个工具 | 「贴出 `python deploy.py --json` 的完整输出，我要看 `ok` 和 `steps`。」 |
| 把 `HW_CONFIG_PATH` 的 `[..]` 当错误去"修复" | 「那一条是预期的，批处理调用时会自动摘除该变量。不要动它。」 |
| 说找不到 HyperMesh 就要你手工填路径 | 「先跑 `python hwmcp/autodetect.py` 列出候选，再按 AGENTS.md 第四节的三种写法选一个。」 |

---

## 为什么这些 prompt 要写这么细

AI 部署这类工具最常犯的错不是能力不足，而是**过度干预**：看到路径不对就去改代码、看到配置缺失就手写一份、
看到某项不是 `[OK]` 就去"修"环境变量。这些动作都会让仓库与本机配置分叉，下次 `git pull` 就冲突。

所以每段 prompt 都做了三件事：

1. **先看再动**（`--dry-run`）
2. **给出唯一判据**（`ok` 字段，而不是"看起来没报错"）
3. **划出禁区**（不许 pip、不许手写配置、不许改代码）

这三条对应 `AGENTS.md` 里的硬约束。prompt 是入口，`AGENTS.md` 是细则——两者指向同一套规则。
