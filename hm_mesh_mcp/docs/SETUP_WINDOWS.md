# Windows 部署清单

从零到能用，按顺序执行。每步都有「预期结果」，对不上就停在那一步排查。

---

## 0. 前置确认

| 项 | 检查命令 | 预期 |
|---|---|---|
| HyperMesh 已安装 | `dir "F:\Program\Altair2021.2\hwdesktop\hm\bin\win64\hmbatch.exe"` | 文件存在 |
| GUI 可执行 | `dir "F:\Program\Altair2021.2\hwdesktop\hw\bin\win64\hw.exe"` | 文件存在 |

> `hmbatch.exe` 与 `hw.exe` 缺一不可：批处理用前者，可见 GUI 模式用后者。**不要**把 `hmopengl.exe` 配给本 MCP（那是交互式 MCP 用的）。

---

## 1. 依赖安装

### 1.1 已有可复用 venv（最快，跳过本节）

```bat
.venv\Scripts\python.exe -c "import mcp.server.fastmcp; print('ok')"
```

输出 `ok` 即完成。否则走 1.2。

### 1.2 联网安装

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.lock.txt
.venv\Scripts\python.exe -c "import mcp.server.fastmcp; print('ok')"
```

预期：`ok`。

> 若报 `No matching distribution found for mcp`，是源不通，换 `https://pypi.org/simple` 或 `https://mirrors.aliyun.com/pypi/simple` 重试。
> **不要**直接 `pip install mcp` —— 会装到 2.x，导入必失败。

### 1.3 离线安装（无网机器）

1. 目标机安装 **Python 3.12 64 位**（`wheels/` 全是 `cp312`）。
2. 从上游取 `wheels/` 目录放在项目根。
3. 执行：

```bat
python -m pip install --no-index --find-links wheels -r requirements.txt
```

预期：末尾出现 `Successfully installed ... mcp-1.27.1 ...`。

---

## 2. 配置 HyperMesh 路径

```bat
copy hypermesh_batch_path.example.txt hypermesh_batch_path.txt
```

编辑 `hypermesh_batch_path.txt` 第一行，改成你的 `hmbatch.exe` 完整路径（正反斜杠均可）。

**预期**：

```bat
.venv\Scripts\python.exe verify_env.py
```

```
[2/4] tool count  : 33
[3/4] executables :
{
  "success": true,
  "selected": "F:\\Program\\Altair2021.2\\hwdesktop\\hm\\bin\\win64\\hmbatch.exe",
  ...
}
[4/4] connectivity: SKIPPED (pass --full to run a real hmbatch probe)
```

---

## 3. 连通性验证（可选，占 license）

```bat
.venv\Scripts\python.exe verify_env.py --full
```

预期：返回 `"success": true`。失败时看返回里的 `stderr`。

> 这一步会真正起一次 `hmbatch.exe`，**占用一个 license 约 10–30 秒**。共享 license 池时请在空闲时段做。

---

## 4. 注册到 MCP 客户端

把 `mcp_config.workbuddy.json` 的内容合并进 `~/.workbuddy/mcp.json`（Windows 下为 `C:\Users\<你>\.workbuddy\mcp.json`），把其中两个路径换成你的仓库绝对路径。

- 文件不存在 → 直接新建，整体写入。
- 文件已有内容 → **只往 `mcpServers` 里加一个 key**，不要覆盖其它条目。已有 `hypermesh` 时新增 `hypermesh-mesh`。

保存后到客户端「连接器管理」页 → 右上角「自定义连接器」→ 对新条目点**信任**。

**预期**：连接器状态变为 `ready`，工具列表出现 33 个（以 `generate_`、`execute_`、`classify_` 等开头）。

---

## 5. 首次使用顺序

模型必须先在 HyperMesh 里打开（GUI 模式），或由脚本显式加载（批处理模式）。

1. `get_hypermesh_meshing_strategy()` —— 读规则
2. `locate_hypermesh()` —— 确认可执行文件
3. `create_gui_listener_tcl(port=47881)` —— 拿到 Tcl
4. **人工**在 HyperMesh 命令窗口 `source` 那个 Tcl（GUI 模式必需）
5. `run_geometry_probe_gui()` —— 探几何
6. `classify_all_solids_from_probe(probe_lines=...)` —— 分类
7. `generate_phase2_finalize_tcl(classify 结果)` → 执行 —— **Phase 2，必做**
8. `generate_batched_drag_hex_tcl` / `generate_batched_plain_tetra_tcl` —— 生成网格脚本
9. `execute_tcl_gui_async` 或 `execute_tcl` —— 执行
10. `write_chinese_meshing_workflow_report` —— 出报告

批处理模式可跳过 3、4 两步，直接用 `execute_tcl`。

---

## 6. 排错对照

| 报错 | 处置 |
|---|---|
| `ModuleNotFoundError: mcp.server.fastmcp` | mcp 装成 2.x，执行 `pip install "mcp==1.27.1"` |
| `No matching distribution found`（离线） | Python 不是 3.12 |
| `Could not find hmbatch.exe` | 路径文件为空或路径写错；改用 `HYPERMESH_BATCH_EXE` 环境变量 |
| `Could not find hw.exe/hwx.exe` | 设 `HYPERMESH_GUI_EXE` 指向 `hwdesktop\hw\bin\win64\hw.exe` |
| 生成脚本被执行器拒绝 | 脚本缺 `MCP_SCRIPT_BEGIN/END` 标记，或未通过生成器 |
| 分类后仍被拒 | Phase 2 未完成（缺 `MCP_FINALIZE_OK`） |
| GUI 执行超时 | listener Tcl 未 source；或端口被占用（改 47882 两侧同步改） |
| `hmbatch` 返回 license 错误 | 并发过高，改用 `*_batched_*` 生成器减少进程数 |
| 工具调用无响应 | 客户端未点「信任」，或 `command` 路径指向不存在的 python |
