# 2026 C 题：微网与外部电网电力调控策略

四问的模型、思路、指定日期表格、数值结果、敏感性与边界见 **[完整解答](docs/solution.md)**。已按附件模板生成五个结果文件。

已完成 [LaTeX 论文 PDF](outputs/pdf/microgrid-paper.pdf)，可编辑入口为 [paper/main.tex](paper/main.tex)。论文采用用户指定的 [CUMCMThesis 模板](https://github.com/latexstudio/CUMCMThesis)，按模板组织章节，并按广东赛区的本次提交要求去掉承诺书、编号页和目录。12 篇参考文献均在正文中引用，表格直接从已验证结果生成，覆盖四问与两轮补充实验。[模板适配说明](docs/template-adaptation.md)、[撰写记录与编译说明](docs/paper-writing-notes.md)、[文献核实笔记](docs/literature-notes.md) 记录结构、写作取舍及来源。运行 `python scripts/build_paper.py` 可重新核对表格并编译论文。

按教师意见完成[逐问修订](docs/paper-revision-teacher.md)：问题重述至总结共 27 页，问题一至四分别为 6、5、6、6 页。每问包括目标函数、分条约束、汇总模型、求解步骤、结果分析和灵敏度检验。完整 PDF 59 页，另外包含摘要、参考文献及完整日期附录；页数口径见修订记录。

全文 46 张表保持正文同等字号和三线表样式，储能表使用单组列，说明融入正文；4 幅数据图采用矢量图。正文不使用下划线，文献引用采用模板上标。当前验收见 [论文验证](paper/validation.json)、[逐表验收](paper/table-style-validation.json)，历次调整见 [三线表核查记录](docs/table-style-audit.md)。

第一轮修订针对预报价值归因、缺少简单基准和增购撤回合约风险，处理依据见 [评审回应](docs/review-response.md)。问题 3、4-3 增加历史光伏/附件 3 融合候选；新小时预报贡献以保留重规划、当前库存、负载修正和当前光伏锚点的严格对照衡量。逐笔交易合约分别报告冻结主调度重计费与重新优化，不能混为一项结果。

第二轮复审已关闭上述三项意见。本轮另补价格感知反馈基准、4—12 月按上月选参的滚动实验及未来年度数据入口，见 [第二轮回应](docs/round2-response.md) 与 [外部验证协议](docs/external-validation-protocol.md)。这些补充独立报告，不根据再次查看同年费用的结果改选下表主方案；真正未见过的外部年度数据仍未获得。

| 问题 | 文件 | 正式评价期总费用 |
| --- | --- | ---: |
| 1：确定性日循环 | [result1.xlsx](outputs/result1.xlsx) | 35,126.95 元/天 |
| 2：固定电价，无日内调整 | [result2.xlsx](outputs/result2.xlsx) | 13,908,175.95 元 |
| 3：固定电价，有日内调整 | [result3.xlsx](outputs/result3.xlsx) | 13,315,835.99 元 |
| 4-2：波动电价，无日内调整 | [result4-2.xlsx](outputs/result4-2.xlsx) | 14,675,844.87 元 |
| 4-3：波动电价，有日内调整 | [result4-3.xlsx](outputs/result4-3.xlsx) | 14,044,885.25 元 |

后四项覆盖 2025-02-01 至 12-31，共 334 天，包含计划、调整及紧急购电费用。每日实际 SOC 从 1 月 1 日 6000 kWh 连续承接。问题 1 有 LP/MILP 最优性验证；后续是因果预测和反馈调度的可行启发式，不声称随机全局最优。

## 阅读顺序与交付

- [解答论文](docs/solution.md)：完整回答四问，包含题面要求的表 1、表 2、表 3。
- [C 类数学建模论文写作 skill](.agents/skills/cumcm-c-paper-writing/SKILL.md)：整理 11 篇参考论文的结构、摘要、逐问论证和图表写法，附阅读页码与可复用大纲；后续可用 `$cumcm-c-paper-writing` 调用。
- [决策与过程记录](docs/decisions.md)、[数据审计](docs/data-audit.md)、[独立建模审查](docs/model-review.md)。
- [评审回应](docs/review-response.md)、[修订实验与完整参数候选](outputs/revision-experiments.json)、[修订情景逐段归档](outputs/revision-dispatch.npz)。
- [第二轮回应](docs/round2-response.md)、[第二轮实验计划](docs/round2-plan.md)、[外部年度验证协议](docs/external-validation-protocol.md)。
- [第二轮实验汇总与逐月选参](outputs/round2/experiments.json)、[新增逐段归档](outputs/round2/dispatch.npz)、[第二轮专项核验](outputs/round2/validation.json)。
- [Excel 模板说明](docs/template-spec.md)：时间标签纠错、列含义、费用口径与验证。
- [汇总数据](outputs/summary.json)、[逐段调度及修订归档](outputs/dispatch.npz)、[输出接口 JSON](outputs/results.json)。
- [物理及因果验证](outputs/validation.json)、[Q1 独立 MILP 验证](outputs/q1-milp-verification.json)、[Excel 验证](outputs/workbook-verification.json)。
- [修订实验专项验证](outputs/revision-validation.json)，覆盖严格信息对照、候选选择、合约路径及新增场景的物理约束。
- [完整源码重放核验](outputs/reproduction-validation.json)：定稿源码在独立输出目录完整重算，3 份 JSON 数值及两份归档的 347 个数组与交付结果完全一致；运行耗时字段不参与相等比较。

原始 `problem/`、`data/raw/` 保持不变。数据与输出中的功率单位 kW、电量 kWh、价格元/kWh、费用元。

## 关键口径

输入时点 00:10 代表 00:00–00:10，功率乘 1/6 小时得到区间电量。模板时间头原本整体偏移 10 分钟，输出已修正，数据不旋转。小时预报按真实发布时间向未来展开。

主结果采用两个单向效率各 90%、不售电、可放弃未利用电量、原计划付费不退款、按交付段最终净调整结算一次；这要求未交付增购仍是可以撤回的计划申报。逐笔已成交增购不可免费撤回的合约另行选参、重新优化，冻结主调度仅换账单的压力测试也单独列出。波动价格按历史预测作决策、真实价格结算。退款、效率、积分与价格先知的替代解释分列敏感性结果。

修订主策略在 1 月固定用纯附件 3 和 0.8 分位热启动，2 月才启用所选光伏融合权重与分位；历史基准同时保留原热启动以复现评审，并新增与主策略共同热启动的版本用于正式比较。参数值只用 1 月选择，但模型族是在看到全年评审反例后扩展，属于同年再分析，不能称作新的外部验证。主方案的实时反馈仍未按价格优化跨时段电池库存，第二轮新增的确定性价格感知反馈单独比较；物理与结算检查不证明经济最优。

后四个 Excel 的“计划购电量”费用列是原计划费；“调整购电量”费用列是原计划费加调整增量费，不含紧急费用，不能与计划表的费用列再次相加。完整总费用在论文及 JSON 中。

## 计算复现

计算使用 Python 3.14、NumPy、SciPy/HiGHS、Matplotlib、openpyxl（仅只读原始或输出 Excel）。在具有这些包的环境执行：

```powershell
python -m pip install -r requirements.txt
python scripts/prepare_data.py
python scripts/solve.py
python scripts/validate_results.py
python scripts/test_contracts.py
python scripts/validate_revision.py
python scripts/verify_q1_milp.py
python scripts/build_report.py
```

`solve.py` 完成 1 月权重/分位候选验证、全年正式策略、可实施历史基准、严格小时预报对照、逐笔合约重新优化及参数/语义敏感性；当前机器约需 5–7 分钟，验算和 Excel 导出另计，本次计算耗时见 `outputs/summary.json` 的 `elapsed_seconds`。主参数只用 1 月选择；2—12 月敏感性不会反过来替换主方案，但这不等同于模型开发未见过全年数据。运行后重新验证以更新结果和代码哈希。

首次从代码复现时，Excel 验证 JSON 要在下述导出步骤完成后生成。`build_report.py` 读取计算结果、物理验证和修订专项验证，生成完整论文并刷新 README 总费表；论文中的 Excel 验证链接在导出后有效。

### 第二轮补充实验

以下流程追加四个价格感知反馈基准和问题 3、4-3 的跨月选参，输出至独立目录，不覆盖主结果或 Excel：

```powershell
python scripts/test_feedback.py
python scripts/test_external_inputs.py
python scripts/evaluate_round2.py
python scripts/validate_round2.py
python scripts/build_report.py --markdown-only
```

`evaluate_round2.py` 默认同时执行反馈与滚动两组实验；完整选择记录、费用分解与 14 条路径保存在 `outputs/round2/`。`build_report.py` 检测到该目录的实验 JSON 后，生成论文第 8.5 节和第二轮回应的数值表；`--markdown-only` 保留已有图文件。计算生成与独立验收分开，只有后者通过才可报告验证通过。

未来数据入口为 `evaluate_round2.py --mode external --future-data ... --output-dir ...`，输入及独立核验命令见 [外部验证协议](docs/external-validation-protocol.md)。外部模式固定参数，按各自历史控制承接库存，不进行新一轮搜索。[合成输入接口验证](outputs/round2/interface-smoke.json) 的 727 项检查通过，仅检验加载、连续状态及验算链；没有新增真实年度数据，合成样例费用也未列作经济证据。

### 论文补充灵敏度与构建

`outputs/paper-study/` 独立保存第一问可用库存、功率、效率的 16 个单日情景（含无储能对照），以及第四问预测价差幅度 ±20% 的 4 条全年路径。价差实验保持原实际结算价格和共同 1 月热启动，不替换主策略。

```powershell
python scripts/evaluate_paper_sensitivity.py
python scripts/validate_paper_sensitivity.py
python scripts/build_paper.py
```

补充实验的 201 项独立验算包括物理边界、现金账单、共同期初库存和问题一原始目标与记录的对偶下界一致。构建器会检查实验源哈希，复用未改变的结果，并调用 `build_paper_evidence.py` 重建逐问图表；原有 656 项表格聚合核对继续运行。只改文字或分页且图表来源未变时可用 `--skip-tables`。最终视觉验收随本次 PDF 保存，重新修改后仍需检查实际渲染。

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
paper/                   LaTeX 正文、参考文献与自动生成表格
outputs/pdf/              排版后的论文 PDF
outputs/                 五个 Excel、调度归档、汇总、验收与图表
```
