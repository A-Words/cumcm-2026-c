# 2026 C 题：微网与外部电网电力调控策略

四问的模型、思路、指定日期表格、数值结果、敏感性与边界见 **[完整解答](docs/solution.md)**。已按附件模板生成五个结果文件。

| 问题 | 文件 | 正式评价期总费用 |
| --- | --- | ---: |
| 1：确定性日循环 | [result1.xlsx](outputs/result1.xlsx) | 35,126.95 元/天 |
| 2：固定电价，无日内调整 | [result2.xlsx](outputs/result2.xlsx) | 13,908,175.95 元 |
| 3：固定电价，有日内调整 | [result3.xlsx](outputs/result3.xlsx) | 13,511,208.12 元 |
| 4-2：波动电价，无日内调整 | [result4-2.xlsx](outputs/result4-2.xlsx) | 14,675,844.87 元 |
| 4-3：波动电价，有日内调整 | [result4-3.xlsx](outputs/result4-3.xlsx) | 14,258,363.92 元 |

后四项覆盖 2025-02-01 至 12-31，共 334 天，包含计划、调整及紧急购电费用。每日实际 SOC 从 1 月 1 日 6000 kWh 连续承接。问题 1 有 LP/MILP 最优性验证；后续是因果预测和反馈调度的可行启发式，不声称随机全局最优。

## 阅读顺序与交付

- [解答论文](docs/solution.md)：完整回答四问，包含题面要求的表 1、表 2、表 3。
- [决策与过程记录](docs/decisions.md)、[数据审计](docs/data-audit.md)、[独立建模审查](docs/model-review.md)。
- [Excel 模板说明](docs/template-spec.md)：时间标签纠错、列含义、费用口径与验证。
- [汇总数据](outputs/summary.json)、[逐段调度及修订归档](outputs/dispatch.npz)、[输出接口 JSON](outputs/results.json)。
- [物理及因果验证](outputs/validation.json)、[Q1 独立 MILP 验证](outputs/q1-milp-verification.json)、[Excel 验证](outputs/workbook-verification.json)。

原始 `problem/`、`data/raw/` 保持不变。数据与输出中的功率单位 kW、电量 kWh、价格元/kWh、费用元。

## 关键口径

输入时点 00:10 代表 00:00–00:10，功率乘 1/6 小时得到区间电量。模板时间头原本整体偏移 10 分钟，输出已修正，数据不旋转。小时预报按真实发布时间向未来展开。

主结果采用两个单向效率各 90%、不售电、可放弃未利用电量、原计划付费不退款、按交付段最终净调整结算一次。波动价格按历史预测作决策、真实价格结算。退款、效率、积分与价格先知的替代解释分列敏感性结果。

后四个 Excel 的“计划购电量”费用列是原计划费；“调整购电量”费用列是原计划费加调整增量费，不含紧急费用，不能与计划表的费用列再次相加。完整总费用在论文及 JSON 中。

## 计算复现

计算使用 Python 3.14、NumPy、SciPy/HiGHS、Matplotlib、openpyxl（仅只读原始或输出 Excel）。在具有这些包的环境执行：

```powershell
python -m pip install -r requirements.txt
python scripts/prepare_data.py
python scripts/solve.py
python scripts/validate_results.py
python scripts/verify_q1_milp.py
python scripts/build_report.py
```

`solve.py` 完成 1 月滚动验证、全年正式策略、预报消融和参数/语义敏感性，当前机器约需 2–3 分钟。主参数只用 1 月选择；2–12 月敏感性不会反过来替换主方案。运行后重新验证以更新结果和代码哈希。

首次从代码复现时，Excel 验证 JSON 要在下述导出步骤完成后生成。`build_report.py` 只需计算与物理验证结果，其论文中的 Excel 验证链接在导出后有效。

### Excel 导出

Excel 使用 Codex bundled Node 和 `@oai/artifact-tool` 导入附件 5 模板，重算并导出；不使用 openpyxl 写文件。这一导出依赖 Codex 工作区运行时，单纯安装 Python 依赖不会获得该工具。当前环境命令：

```powershell
$artifactNode = 'C:/Users/A_Words/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
& $artifactNode scripts/export_results.mjs
& $artifactNode scripts/export_results.mjs --verify
```

其他机器需安装/提供同等 artifact-tool 运行时，并调整导出器中 bundled Node/Python 的默认路径。模板检查、已保存文件预览分别可用 `--inspect`、`--preview-saved`。默认导出包含重算、错误扫描、渲染和保存后全量核对。首次在 Codex 技能工作流中实际填充前的标记步骤见 [模板说明](docs/template-spec.md)。

已执行全部数值核验、Q1 MILP 交叉验证和五个 Excel 的全量值对照及渲染检查。未启动桌面 Excel 做交互式复算。图表同时提供 PNG/SVG，位于 `outputs/figures/`。

## 目录

```text
problem/                 原题 PDF
data/raw/                原始附件与空白模板
data/processed/          对齐数组、统计与源文件哈希
scripts/                 预处理、预测/优化、回测、验证与导出
docs/                    完整解答、建模过程和审查
outputs/                 五个 Excel、调度归档、汇总、验收与图表
```
