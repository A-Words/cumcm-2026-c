# CUMCMThesis 模板与论文结构适配记录

## 来源及约束

用户指定 [latexstudio/CUMCMThesis](https://github.com/latexstudio/CUMCMThesis)，并明确要求广东赛区论文中没有承诺书、编号页和目录。这里按这三项用户要求配置，不将本次设置表述为对其他赛区或其他年份规则的核实。

模板固定到提交 [`38d1f216bec3c9ffffb7dd09bf6b6c54f486b130`](https://github.com/latexstudio/CUMCMThesis/tree/38d1f216bec3c9ffffb7dd09bf6b6c54f486b130)。仓库内 `paper/cumcmthesis.cls` 和 `paper/cumcm2026.sty` 直接来自该提交，分别为 2026/08/26 v2.9 和 2026/08/23 v1.0；均未修改。文件 SHA-256、选项和来源记录在 `paper/template-source.json`。上游快照未见单独的 LICENSE 文件，保留原文件内容及署名，不附加推测的许可证。

`cumcmthesis.cls` 原文件有 7 处 Git 空白格式提示（行尾空格或空格后接制表符）。为保持与固定提交逐字节一致，原样保留；排除该上游文件后，本次修改通过 `git diff --check`。

## 页面配置

```latex
\documentclass[withoutpreface,bwprint]{cumcmthesis}
\usepackage{cumcm2026}
```

`withoutpreface` 关闭模板的承诺书与编号页；主文件不调用 `\tableofcontents`。仍调用 `\maketitle`，因此 PDF 第一页直接包含论文标题、摘要及关键词，页码从 1 开始。摘要使用模板环境，结束后正文另起一页。没有学校、队号或队员占位字段。

字号、行距、页边距、章标题、图表标题和页脚以模板为准。必要的本地适配仅包括：已有 Windows 字体映射；GB/T 7714 参考文献；长网址换行及浮动体控制；数学简写命令；PDF 书签去除视觉细空格；附录子节显示 A.1、A.2 等字母编号。沿用示例的 `bwprint` 选项；本快照实际链接样式由模板的 `allcolors=black` 和主文件的 `hidelinks` 确定，原有两幅数据图仍保留颜色。

## 三线表适配

按用户要求，所有表格尽量对齐上游 `example.tex` 的“标准三线表格”：顶底线 `1.5pt`、中线 `1pt`。这是所选模板的具体示例值，不称为 booktabs 的唯一通用标准。表体采用模板正文 `12.05pt`，表题为相同字号并加粗，列边留白 `\tabcolsep=6pt`，行距系数 `\arraystretch=1.38`；长表显式设置行距，因为类文件的 `tabular` 包装不直接覆盖 `longtable`。以上设置位于论文主文件及生成表格中，不修改上游类文件。

不画竖线、双线或日期分组的额外中线；日期分组使用 `\addlinespace`，跨页表重复三线和列标题。购电时段、紧急事件按日期纵向展开，保留正常字号；原表下小字解释全部迁入正文或附录导语，单位保留在表题、表头或明确的数据行中。当前主文和附录实际输入 31 张表，另有 2 份未引用生成模块。来源、具体设置和数据保留审计见 [`table-style-audit.md`](table-style-audit.md)。

## 章节映射与写作理由

参考上游 `example.tex` 的章节骨架，按本题四问细化，避免把模板中的排版演示当作论文内容。

| 论文位置 | 对应文件 | 内容及组织理由 |
| --- | --- | --- |
| 标题、摘要、关键词 | `main.tex`、`sections/abstract.tex` | 概括问题、方法、主费用结果和结论边界，直接作为首页。 |
| 一、问题重述 | `sections/problem.tex` | 提炼微网背景、任务和数据对齐，不重复建模推导。 |
| 二、模型的假设 | `sections/assumptions.tex` | 集中列明效率、弃电、结算、信息和连续库存约定。 |
| 三、符号说明 | `sections/symbols.tex` | 统一十分钟电量、功率、价格、库存和计划符号。 |
| 四、问题分析 | `sections/analysis.tex` | 说明四问递进关系及预测、规划、反馈的分工，定位相关文献。 |
| 五、模型的建立与求解 | `sections/model.tex` | 先写统一物理模型，再按问题一至四展开；输入 `physical-model.tex`、`q1.tex` 至 `q4.tex`。 |
| 六、结果分析与模型检验 | `sections/results.tex` | 统一呈现主账单、历史基准、严格信息对照、替代合约、价格反馈与跨月评估。 |
| 七、模型评价与推广 | `sections/evaluation.tex` | 讨论优势、解释敏感性、局限及未来适用边界。 |
| 八、总结 | `sections/conclusion.tex` | 回答四问，保留确定性最优与因果启发式的区别。 |
| AI 工具使用声明 | `sections/ai-statement.tex` | 如实说明实际辅助范围，不预填个人信息或人工审核承诺。 |
| 参考文献 | `references.bib` | 12 篇均有对应正文引用，题录与阅读深度见文献笔记。 |
| 附录 A—C | `sections/appendix.tex` | 指定日期完整表、逐月参数与费用差额、数据计算及复现说明。 |

重组保留了原正文的全部 18 个数学展示环境和 14 个已有标签，未改动计算公式或主结果。新文献仅补充已有方法背景，不能据此将经验分位控制改称分布鲁棒最优模型，或把同年滚动回顾改称独立泛化验证。

## 构建与验收

运行 `python scripts/build_paper.py`。构建器先从原归档重新聚合生成表格，再在 `tmp/paper-build/` 内的源码快照执行 XeLaTeX、BibTeX8、XeLaTeX 两遍。隔离快照避免编辑器自动预览留下的辅助文件影响引用编号；不改全局 TeX 配置。

验收包括 656 项数值核对、模板文件哈希、正文与题录引用集合、PDF 首尾及全页渲染、被排除页面的文本检查、字体嵌入、公式和长表边界。最终记录在 `paper/validation.json`。原始题目、附件、模型代码、数值归档和五份 Excel 均不因排版迁移而变化。

本轮三线表改版另做独立排版前后比较：31 张实际表的 1,142 个字段、包含未引用模块时的 1,169 个字段均通过；归档聚合的 656 项核对也通过。最终构建已完成全页目视核查，并对修订页面重新渲染，检查了同等字号、重复表头、日期块、无表下小字及正常段落衔接。实际 PDF 中 38 个表段的 114 条横线和表内普通文字字号也通过测量。最终页数和交付状态见 `paper/validation.json`，逐表位置及样式验收见 `paper/table-style-validation.json`。
