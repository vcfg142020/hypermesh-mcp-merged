# HyperMesh MCP 配置教程

照着做，每步都有**预期输出**可以对照。全程约 10 分钟，其中一半是等 HyperMesh 启动。

> 当前状态：`mcp.json` 我已经替你写好了，你只需完成**第 1 步自检**和**第 4 步信任**。
> 如果你换了机器或改了安装路径，从第 1 步重新走。

---

## 总览

```
① 自检环境  →  ② 确认 Python 路径  →  ③ 写 mcp.json  →  ④ 界面里信任  →  ⑤ 验证连通  →  ⑥ 干活
   doctor.py         which python        （已就绪）        必须手动做        hm_status      第一个算例
```

前两步是排查，第 3 步是配置，**第 4 步是唯一容易漏掉的一步**——不信任就不会激活。

---

## 第 1 步：环境自检

打开命令行（Git Bash / PowerShell / cmd 都行），执行：

```bash
cd <仓库路径>/hwmcp
python doctor.py
```

### 预期输出

```
====================================================================
HyperMesh MCP 环境自检
====================================================================
[OK]  Python 版本 >= 3.9    当前 3.13.14  (.../python.exe)
[OK]  服务端模块可导入    工具数 20
[OK]  HyperMesh 可执行文件存在    F:\Program\Altair2021.2\hwdesktop\hm\bin\win64\hmopengl.exe
[OK]  用的是 GUI 版 hmopengl.exe（不是 hmbatch）    hmopengl.exe
[OK]  注入脚本 _sock.tcl 存在    ...\hwmcp\_sock.tcl
[OK]  本机空闲端口可分配    示例端口 2586

-- 正在启动 HyperMesh，首次约 15-20 秒，请稍候 --
[OK]  HyperMesh 进程启动并接受连接    端口 2587
[OK]  求解器 profile 已加载    profile = OptiStruct
[OK]  可写入模型（建 component 成功）    当前 comps = 1
[OK]  可建几何（平面曲面）    surfaces = 1

====================================================================
结论：全部通过，可以接入 MCP。
====================================================================
```

**看到「结论：全部通过」才继续往下走。** 这一步会真的启动一次 HyperMesh、建一个 component、建一块曲面，所以它通过就代表整条链路是通的。

### 如果没通过

| 报错项 | 处置 |
|---|---|
| `HyperMesh 可执行文件存在` 失败 | 你的 HyperWorks 不在 `F:\Program\Altair2021.2`。改 `hm_session.py` 里的 `DEFAULT_EXE`，或设环境变量 `HWMCP_HM_EXE` |
| `用的是 GUI 版` 失败 | 指向了 `hmbatch.exe`。改成同目录下的 `hmopengl.exe`，否则材料/属性卡片会报 `Invalid input` |
| `进程启动并接受连接` 失败 | 先 `taskkill /F /IM hmopengl.exe` 清掉僵尸进程再试 |
| `profile 已加载` 显示 `HyperMesh` 而非 `OptiStruct` | 同第二条，用错可执行文件了 |

---

## 第 2 步：确认 Python 路径（必须用绝对路径）

`mcp.json` 里**不能**写 `"python"`。原因：客户端启动子进程时的 PATH 与你终端里的 PATH 不一定相同，Windows 下 `python` 很可能解析到 `WindowsApps\python.exe` 这个微软商店存根，它启动后立刻退出，界面就报 `MCP error -32000: Connection closed`（实测 153 ms 断开）。

查你机器上的真实路径：

```bash
which python && python -V
```

### 预期输出

```
python
Python 3.13.14
```

把它转成 Windows 正斜杠格式填进 `mcp.json`：

```
python
```

> 用 `python` 就够了：客户端按 PATH 解析，升级 Python 也不用改配置。
> 若机器上有多个 Python，用 `where python` 第一行填**绝对路径**，避免解析到别的解释器。

---

## 第 3 步：写入 `mcp.json`

文件位置：`C:\Users\<你的用户名>\.workbuddy\mcp.json`

**注意是 `mcp.json`，不是 `.mcp.json`**（后者是项目级配置，用户级不生效）。

当前内容应当是：

```json
{
  "mcpServers": {
    "hypermesh": {
      "command": "python",
      "args": [
        "<仓库路径>/hwmcp/server.py"
      ],
      "env": {
        "HWMCP_AUTOSTART": "1",
        "HWMCP_HM_VERSION": "2021.2"
      }
    }
  }
}
```

### 字段含义

| 字段 | 作用 | 什么时候改 |
|---|---|---|
| `command` | Python 解释器的**绝对路径** | 客户端升级导致路径失效时 |
| `args[0]` | server.py 的绝对路径 | 移动了 `hwmcp` 目录时 |
| `env.HWMCP_HM_EXE` | HyperMesh 可执行文件 | 换了 HyperWorks 安装路径时 |
| `env.HWMCP_AUTOSTART` | `1` = 连接后后台预热 HyperMesh；`0` = 首次调用才拉起 | 不想一开客户端就占用一个 HyperMesh 时设 `0` |

### 如果你已有其他 MCP server

**合并**，不要覆盖。把 `hypermesh` 这一段加到现有 `mcpServers` 对象里，兄弟节点之间用逗号隔开：

```json
{
  "mcpServers": {
    "已有的服务": { "...": "..." },
    "hypermesh": { "...": "..." }
  }
}
```

写完用这行验证 JSON 没写坏：

```bash
python -c "import json,pathlib;d=json.loads((pathlib.Path.home()/'.workbuddy'/'mcp.json').read_text(encoding='utf-8'));print('JSON 合法，已注册：',list(d['mcpServers']))"
```

预期输出：

```
JSON 合法，已注册： ['hypermesh']
```

---

## 第 4 步：在界面里信任连接器 ← **最容易漏**

新写入的 MCP server **不会自动激活**，必须手动信任一次。

1. 打开**连接器管理页**（左侧栏或设置里的「连接器 / Connectors」入口）
2. 在页面**右上角**找到「自定义连接器」入口并点开
3. 列表里应出现 `hypermesh`
4. 点它旁边的**信任 / Trust**（有的版本叫「启用」）
5. **重启客户端**，让新进程按新配置加载

### 怎么确认成功了

重启后看连接器的状态标记，应当是**已连接 / connected**，而不是待授权或未启用。

> 如果列表里根本看不到 `hypermesh`：说明 `mcp.json` 没被读到。回头检查文件名（`mcp.json`）、JSON 是否合法、路径是否真的有 `server.py`。

---

## 第 5 步：验证连通

重启后在对话里直接说：

> **用 hypermesh 看一下当前会话状态**

或者更明确：

> **调用 hm_status 工具，告诉我 profile 和实体数量**

### 预期行为

1. **第一次会卡 15–25 秒** —— 这是 HyperMesh 在初始化，正常
2. 返回类似这样的 JSON：

```json
{
  "running": true,
  "port": 2587,
  "profile": "OptiStruct",
  "entities": {"comps": 0, "mats": 0, "props": 0, "elems": 0, "nodes": 0, ...}
}
```

只要看到 `"profile": "OptiStruct"`，就说明整条链路已经打通。

### 如果工具列表里没有这 20 个工具

说明连接器没启用成功，回到第 4 步。`hm_status` 是最轻的工具，先验证它，别一上来就跑复杂算例。

---

## 第 6 步：跑第一个算例

把下面整段话发给 AI，它会自己串起工具调用：

> **用 hypermesh 做一个 200×200 的板，10mm 四边形网格，钢材 E=210000 泊松比 0.3，板厚 2mm。左边（x=-100）那排节点全约束，中心点加 -100 的 Z 向力，建一个静力工况，导出 OptiStruct 文件到 `<仓库路径>/hwmcp/workspace/test_plate.fem`，然后告诉我 deck 里有多少单元和节点。**

### 预期结果

- 网格：**400 个 CQUAD4 / 441 个 GRID**（200/10 = 20，20² = 400）
- 约束：左边界 **21 个节点**（y 从 -100 到 100，步长 10）
- deck 体检报告里能看到：

```
GRID      441
CQUAD4    400
PSHELL    1
MAT1      1
SPC       126
FORCE     1
SUBCASE   1
"spc_detail": {"nodes": 21, "fixed_dofs": 63}
```

`SPC` 报 126 是正常的：OptiStruct 的 SPC 卡片一行一个自由度，21 个节点 × 6 个自由度 = 126 行，
其中真正固定的 63 个（21 × dofs[1,2,3]）由 `spc_detail.fixed_dofs` 单独给出。

- case control 段完整：

```
SUBCASE        1
LABEL static1
SPC =        1
LOAD =        2
```

如果 `SPC =` / `LOAD =` 缺失，说明工况没绑好，让 AI 重新执行 `hm_create_loadstep`。

---

## 常用对话句式

工具是给 AI 调的，你正常说需求即可。几个好用的句式：

| 你想做的事 | 怎么说 |
|---|---|
| 查状态 | 「看一下 HyperMesh 当前状态」 |
| 换网格尺寸 | 「把网格改成 5mm 重划」 |
| 按位置选节点 | 「找出 z=0 那条边上所有节点」 |
| 改材料 | 「把弹性模量改成 70000」 |
| 换求解器 | 「改导出成 Abaqus 格式」 |
| 工具没覆盖的操作 | 「执行这段 Tcl：`*createmark nodes 1 all`」 |

`hm_run_tcl` 是逃生口，工具集没覆盖的面板操作都能用它直接下发 Tcl。

---

## 故障速查

| 现象 | 原因 | 处置 |
|---|---|---|
| `MCP error -32000: Connection closed` | ① `command` 用了 `python` 而非绝对路径，解析到商店存根立即退出；② `server.py` 在进入读取循环前同步等 HyperMesh，握手无人应答 | 用绝对路径；二者均已修复，若再出现跑 `python doctor.py` 定位 |
| `can not find channel named stdout`（HyperMesh 弹窗） | 启动 HyperMesh 时把 stdout 丢了，`_sock.tcl` 的 `flush stdout` 中断整个脚本，socket 服务没建起来 | 已修：stdout 重定向到 `_hm_session.log`，且 Tcl 侧 `catch` 兜底 |
| 工具调用全部超时 | HyperMesh 进程崩了，或死锁 | 已修（启动与 IO 锁分离）；仍出现则 `taskkill /F /IM hmopengl.exe` |
| 首次调用等超过 3 分钟 | 启动受阻 | 命令行跑 `python doctor.py` 看卡在哪一步，再看 `hwmcp/_hm_session.log` |
| `Invalid input` 写材料 | 用了 batch 版可执行文件 | 换 `hmopengl.exe` |
| `FatalError ... batch mode` | 清模型前少了应答 | 用 `hm_new_model` 工具，别手写 `*deletemodel` |
| deck 里没有 `SPC =` / `LOAD =` | 工况没绑定载荷集 | 重新调 `hm_create_loadstep`，两个载荷集都要给 |
| 载荷加到了所有节点上 | 省略了 `nodes` 参数 | 用 `hm_find_entities` 先取 id 列表再传 |
| 改了配置但没生效 | 客户端只在启动时扫描 MCP 列表 | 完全退出（含托盘）再重开 |
| `JSON 语法错` | 路径里用了反斜杠 | 全部改成正斜杠 `/` |

---

## 关闭 / 卸载

| 想做的事 | 做法 |
|---|---|
| 临时不用，但不占进程 | `mcp.json` 里把 `HWMCP_AUTOSTART` 改成 `"0"` |
| 彻底停用 | 连接器管理页里关闭 `hypermesh`，或从 `mcp.json` 删掉这一段 |
| 清理残留进程 | `taskkill /F /IM hmopengl.exe` |
| 清临时产物 | 删 `hwmcp/workspace/` 下的 `.hm` / `.fem`，以及运行产生的 `hwmcp/command*.tcl` |

---

## 相关文件

| 文件 | 用途 |
|---|---|
| `doctor.py` | 环境自检（本教程第 1 步） |
| `README.md` | 工具速查、架构、完整能力边界 |
| `HANDOFF.md` | 全部实测 Tcl 签名、踩过的坑（改代码时看这个） |
| `_e2e.py` | 18 步端到端测试，改完代码跑一遍 |
