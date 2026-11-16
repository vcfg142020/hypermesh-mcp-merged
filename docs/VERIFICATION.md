# 验证报告（摘要）

> 完整逐工具报告由 `python hwmcp_merged/make_report.py` 在本机生成
> （`out/MCP工具合并与验证报告.md`），内含每次调用的原始返回，**不随仓库发布**——
> 原始返回里带本机绝对路径。这里只保留可公开的结论与数值证据。

- 验证日期：2026-11-16
- 被测版本：`1.0.0-merged`（54 个工具）
- 环境：HyperWorks 2021.2 + `hmopengl.exe`（GUI 通道）/ `hmbatch.exe`（批处理通道）
- 耗时：56 秒（含 1 次 GUI 冷启动 22 秒 + 9 次 hmbatch 进程）

---

## 一、总结论

| 指标 | 结果 |
|---|---|
| 工具覆盖 | **54 / 54**，无遗漏 |
| 检查条目 | 71 条（54 个工具 + 17 条附加断言） |
| PASS | **65** |
| FAIL | **0** |
| N/A | 6（原因见下） |
| 数值准确性断言 | 9 条，**全部通过** |

6 条 N/A 都不是失败：

- 5 条属"可见 GUI listener"族（`start_hypermesh_gui_listener`、`run_geometry_probe_gui`、
  `execute_tcl_gui`、`execute_tcl_gui_async`、`automesh_surfaces_gui`）：需要人先在 HyperMesh
  界面里 `source` 监听脚本，自动跑会挂住，属设计约束而非缺陷。
- 1 条是 `hm_midmesh_extract` 在 B 阶段（纯壳模型无实体）跳过，C 阶段已 PASS。

---

## 二、分阶段设计

| 阶段 | 内容 | 是否占 license | 条目 |
|---|---|---|---|
| A | 离线：纯生成器 / 规则表 / 路径探测 / 白名单负向 | 不占 | 33 |
| B | 交互：常驻 GUI，跑完整板壳算例并导出 deck | 1 个 | 28 |
| C | 实体：造 `*solidblock` 后跑 MidMesh | 1 个 | 5 |
| D | 批处理：真起 `hmbatch` 做自动网格 | 每次 1 个 | 5 |

阶段之间各自重启 HyperMesh 会话，避免前一阶段的模型状态污染后一阶段。

---

## 三、数值准确性证据

验证不只看"没报错"，而是对照解析解与手算值：

| 断言 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 200×200 板 / 10 mm 四边形网格 | 400 CQUAD4 / 441 GRID（20×20 / 21×21） | 400 / 441 | 通过 |
| 左边界（x = −100）节点选取 | 21 个 | 21 | 通过 |
| deck 逐卡计数 | GRID 441、CQUAD4 400、PSHELL 1、MAT1 1、SPC 126、FORCE 1、SUBCASE 1 | 完全一致 | 通过 |
| case control | `SUBCASE 1` + `SPC = 1` + `LOAD = 2` | 一致 | 通过 |
| MidMesh（10 mm） | 400 个 2D + 80 个 1D 边单元 | 400 / 80 | 通过 |
| `*solidblock` 造体 | 1 个 solid | 1 | 通过 |
| `automesh_surfaces`（20 mm） | 100 单元 / 121 节点 | 100 / 121（读产物文件复核） | 通过 |
| SPC 行数 | 21 节点 × 6 dof = 126 | 126 | 通过 |
| `hm_run_tcl` 返回值透传 | 与 Tcl 表达式一致 | 一致 | 通过 |

> SPC 126 行不是过约束：`*loadcreateonentity_curve` 按 6 个 dof 标志位逐个建实体，
> 每个被约束节点产生 6 行，与上游实现逐字节一致。

---

## 四、验证过程中发现并已处理的问题

以下四条都是实测踩出来的，前三条已在包装层修掉，第四条是上游既有行为，仅记录。

### 1) `HW_CONFIG_PATH` 会让 `hmbatch` 启动即失败

症状：批处理族全部 `returncode=1`，stdout 只有
`Tcl/Tk script error: Invalid args to hm_framework (batch mode)`，脚本一行未执行。

原因：`HW_CONFIG_PATH` 指向自定义 GUI 配置目录时，`hmbatch` 启动阶段会执行
`hm_framework getpulldowns`，该命令在 batch 模式无意义。

处置：`merged_server._batch_call()` 在调用批处理族时临时摘除该变量，返回后恢复。
GUI 族保留（它需要这份配置）。

### 2) `hmbatch` 的退出码不等于成败

症状：脚本明明跑完并打印 `End of command file - terminating.`，退出码却是 1。

原因：`hmbatch.exe` 的退出码 = 脚本**最后一条命令的返回值**。`set n 1` 收尾就会得到 1。

处置：`_normalize_batch_result()` 做可追溯归一化——只在"stdout 含结束标记且不含
Tcl 错误"时把 `returncode` 归零，并把原始值保留在 `raw_returncode` 字段里，不掩盖真实失败。

### 3) `*solidblock` 是 12 个参数，不是 6 个

`*solidblock x0 y0 z0  Lx 0 0  0 Ly 0  0 0 Lz`，且当前 component 必须已存在。
按 6 参数调用会返回含糊的 `HyperMesh 报错：0`。

### 4) `generate_cutsection_spin_hex_tcl` 的 `spin_axis_point` 是运行期必填（上游缺陷）

该参数缺失时运行期报参数错误，但它**不在 `inputSchema.required` 里**，客户端无法提前校验。
属上游 schema 与实现不一致，未擅自修改上游代码，仅在此记录。调用时请显式传
`spin_axis_point`。

---

## 五、可复现性

```bash
# 全量（约 56 秒，起 1 次 GUI + 9 次 hmbatch）
python hwmcp_merged/verify_tools.py

# 只跑批处理族（不占 GUI license，约 5 秒）
python hwmcp_merged/verify_tools.py --phase=D

# 重新生成本地完整报告
python hwmcp_merged/make_report.py
```

> 跑之前确认没有别的 HyperMesh 实例在跑：每个实例各借一个 license，且模型互不相通。

环境信息（HyperWorks 版本、安装位置、Python 解释器、许可方式）由
`hwmcp/autodetect.py` 在运行时探测，报告里不含写死路径；换机重跑会自动反映新环境。
