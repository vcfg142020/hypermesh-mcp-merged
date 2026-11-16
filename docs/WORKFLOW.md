# 双机工作流：公司用完推，回家拉下来继续

目标：同一份代码在两台机器上都能直接跑，**切换机器不需要改代码、不需要改配置**。

前提假设：两台机器都装了 HyperWorks，但**版本可能不同、安装路径一定不同**。这正是关键——
一切与环境有关的东西都不能进仓库。

---

## 一、设计原则（三条，先讲清为什么）

| 原则 | 原因 | 落地方式 |
|---|---|---|
| **代码进 Git，环境不进 Git** | 安装路径、Python 路径、license 服务器地址都是机器私有的 | 所有路径运行时由 `hwmcp/autodetect.py` 算出；`.gitignore` 排除 `out/`、`runs/`、`*_path.txt`、`*.bak` |
| **差异只放在环境变量里** | 环境变量是"本机覆盖"，天然不产生 diff | `HWMCP_HM_VERSION` / `HWMCP_HM_EXE` / `HYPERMESH_BATCH_EXE` |
| **配置模板 + 生成器，不手工编辑** | 手写 `mcp.json` 时最容易把某台机器的绝对路径抄进去 | `python configure.py --write` 每次按当前机器重新生成 |

一句话：**仓库里不出现任何 `C:\`、`D:\`、`F:\` 开头的真实路径。**
`grep -rn "F:/Program" .` 在仓库里应当只命中文档里的示例占位符。

---

## 二、首次部署（两台机器各做一次）

```bash
git clone https://github.com/vcfg142020/hypermesh-mcp-merged.git
cd hypermesh-mcp-merged

python hwmcp_merged/merged_server.py --doctor   # 静态自检，<1 秒
python configure.py --write                     # 生成并写入客户端 mcp.json（会自动备份原文件）
python hwmcp/doctor.py                          # 真启动 HyperMesh 做读写测试，30-60 秒
```

`configure.py --write` 会自动选对路径，**你不需要知道 HyperMesh 装在哪**。

如果第 2 步探测到的版本不是你想要的（多版本并存时），锁一下：

```bash
python configure.py --write --version 2021.2
```

它写入的是 `HWMCP_HM_VERSION=2021.2`，**不是绝对路径**——所以这份配置本身是可以跨机器用的。

---

## 三、日常循环

### 公司收工前（3 条命令）

```bash
git status                      # 确认没有把 out/ 或本机配置加进来
git add -A && git commit -m "..."   # 只提交代码与文档
git push
```

推之前先自检一遍，避免把"只在我这台机器上能跑"的东西推上去：

```bash
python hwmcp_merged/merged_server.py --doctor
git diff --cached | grep -nE "^\+.*([A-Z]:[/\\\\]|/Users/|/home/)" && echo "⚠ 提交里出现了绝对路径"
```

### 回家（2 条命令）

```bash
git pull
python configure.py                 # 只打印，看看探测结果对不对（不会改文件）
```

- **配置不需要重做**：`mcp.json` 指向的是仓库里的 `merged_server.py`，仓库路径没变就不用动。
- **如果家里 HyperWorks 版本不同**：不用改配置。`autodetect` 会自己找到，或者你在家里那份
  `mcp.json` 里把 `HWMCP_HM_VERSION` 改成家里的版本即可——这个改动只在本机生效，不进 Git。

### 回家发现跑不起来？

```bash
python hwmcp_merged/merged_server.py --doctor
```

它会直接告诉你缺哪一环（Python 版本 / `_sock.tcl` / HyperMesh 可执行文件 / hmbatch / 工具表）。
绝大多数情况是「HyperWorks 装在不同盘」——这一步 `autodetect` 已经覆盖了，除非你把安装目录
改成了不含 `Altair` 字样的名字；那种情况用 `HWMCP_HM_EXE` 显式指定一次即可。

---

## 四、两台机器环境差异对照

| 项目 | 公司 | 家里 | 会不会进 Git |
|---|---|---|---|
| 仓库路径 | `F:\work\hypermesh-mcp` | `D:\code\hypermesh-mcp` | 否（`configure.py` 运行时算） |
| Python 解释器 | 客户端自带 3.13 | 系统 3.11 | 否（`sys.executable`） |
| HyperWorks 版本 | 2021.2 | 2025 | 否（`autodetect` / `HWMCP_HM_VERSION`） |
| hmbatch 路径 | `F:\Program\Altair2021.2\...` | `C:\Program Files\Altair2025\...` | 否（`autodetect` 写入 `HYPERMESH_BATCH_EXE`） |
| license | 内网浮动 | 本机或 VPN | 否（`SPLM_LICENSE_SERVER`） |
| 验证产物 `out/` | 本机生成 | 本机生成 | 否（`.gitignore`） |

---

## 五、分支策略（单人或小团队够用）

| 分支 | 用途 | 推送时机 |
|---|---|---|
| `main` | 任何一台机器 `git pull` 后都能直接跑的状态 | 只在 `--doctor` 通过后推 |
| `wip/xxx` | 在公司做到一半、回家接着做 | 随时推，`main` 保持可用 |

做实验性改动时：

```bash
git switch -c wip/try-midmesh-batch
# ... 改 ...
git push -u origin wip/try-midmesh-batch   # 回家 git switch wip/try-midmesh-batch 接着干
```

单人维护时不必开 PR，`wip/*` 验证通过后 `git switch main && git merge --ff-only wip/xxx` 即可。

---

## 六、同一台机器上别维护两份代码

比"两台机器分叉"更常见、更难查的是**一台机器上两份代码**：一个地方是运行副本（客户端 `mcp.json`
的 `args` 指向它），另一个地方是仓库副本（`git push` 用它）。改了一处忘了另一处，客户端就会跑旧代码，
症状往往是"我明明改了却没生效"。

规则：**一个事实来源，其余都是它的下游。**

| 目录 | 身份 | 操作 |
|---|---|---|
| `<仓库>/`（clone 下来的那份） | 唯一事实来源 | 改代码、`git commit`、`git push` 都在这里 |
| 任意运行副本 | 只读下游 | 客户端 `args` 指向它；只能从仓库覆盖过来，不能反向改 |

同步（Windows Git Bash，`cp -r` 即可，无需 rsync）：

```bash
R=/f/work/hypermesh-mcp-merged        # 仓库
U=/f/run/hwmcp_merged                 # 运行副本
for d in hwmcp hwmcp_merged; do
  find "$R/$d" -name '*.py' -o -name '*.tcl' | while read f; do
    t="$U/${f#$R/}"; mkdir -p "$(dirname "$t")"; cp "$f" "$t"
  done
done
cp "$R/configure.py" "$U/../configure.py" 2>/dev/null || true
python "$U/merged_server.py" --doctor       # 同步后必须复验
```

**判断自己有没有踩这个坑**：改动一行代码、重启客户端、行为没变 → 第一件事是看
`mcp.json` 里 `args` 指向哪个目录，而不是怀疑代码写错了。

最省事的做法其实是**只留一份**：把仓库 clone 到你日常使用的位置，`mcp.json` 直接指向仓库里的
`merged_server.py`，从此不存在同步问题。（仓库里已 gitignore `__pycache__`、`out/`、`_sock.log`，
在仓库目录直接跑不会污染 `git status`。）

---

## 七、常见误区

1. **把 `mcp.json` 提交进仓库** —— 里面一定有绝对路径，换机即失效。仓库只放 `mcp.json.example`。
   `configure.py --write` 写的是客户端配置目录（`~/.workbuddy/mcp.json`），不在仓库里，这是有意的。
2. **提交 `hm_mesh_mcp/hypermesh_batch_path.txt`** —— 已 gitignore。需要固定路径时用环境变量。
3. **两台机器各自改一份代码** —— 改完不推，过几天两边分叉。要么推，要么建 `wip/*` 分支推。
4. **在公司提交了验证产物** —— `out/` 里可能有客户模型名、deck 内容。已 gitignore，不要 `git add -f`。

---

## 八、一句话总结

> 仓库只装**逻辑**，机器只装**路径**。路径由 `autodetect` 现算，`configure.py` 一键落盘，
> 于是"公司用完推、回家拉下来"就退化成了普通的 `git push` / `git pull`。
