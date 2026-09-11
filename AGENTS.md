# Repository Guidelines

## 项目结构与模块组织

- `scripts/`：数据预处理、优化模型（`model.py`）、反馈控制、回归测试（`test_*.py`）、验算与导出脚本。
- `problem/`、`data/raw/`：原始题目、附件和 Excel 模板，保持原样；`data/processed/`：对齐后的数组与审计哈希。
- `docs/solution.md`：完整解答；`docs/modeling/`：建模假设与数据口径；`docs/reviews/`：评审计划与回应；`docs/paper/`：论文写作及格式记录。
- `paper/`：LaTeX 源码、上游模板与生成表格。
- `outputs/deliverables/`：最终 PDF 和五个 Excel；`outputs/main/`：主结果及验算；`outputs/experiments/`：各组实验及验算；`outputs/verification/`：跨产物验收；`outputs/figures/`：图表。临时文件放入已忽略的 `tmp/`。

## 构建、测试与开发命令

使用 Python 3.14，在仓库根目录执行：

| 命令 | 用途 |
| --- | --- |
| `python -m pip install -r requirements.txt` | 安装固定版本的数值计算依赖。 |
| `python scripts/prepare_data.py` | 对齐原始数据并生成审计记录。 |
| `python scripts/solve.py` | 重算主策略与修订实验。 |
| `python scripts/evaluate_round2.py` | 将补充实验结果写入 `outputs/experiments/round2/`。 |
| `python scripts/build_report.py` | 验算后更新 Markdown 解答、README 总费用和图表。 |
| `python scripts/build_paper.py` | 重新生成并核对表格，编译论文；PATH 中须有 XeLaTeX 和 BibTeX。 |

Excel 导出依赖 Codex 内置 Node 与 `@oai/artifact-tool`。按 README 配置运行时后，依次执行 `node scripts/export_results.mjs`、`node scripts/export_results.mjs --verify`。openpyxl 仅用于读取 Excel。

## 代码风格与命名约定

Python 使用 4 空格缩进，JavaScript 使用 2 空格；统一 UTF-8 编码和 LF 换行。Python 函数及模块用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`。目前未配置自动格式化或代码检查工具。

## 论文标准与 LaTeX 模板

论文编写与编排遵循 **[GB/T 7713.2-2022《学术论文编写规则》](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=0B963916637B8F34B295FCF4A51A1BE5)**。修改章节结构、摘要、图表、公式、量和单位时，核对相应条款并记录依据。

采用 [CUMCMThesis](https://github.com/latexstudio/CUMCMThesis) 实现排版，固定版本与文件哈希见 `paper/template-source.json`。保持上游 `paper/cumcmthesis.cls` 和 `paper/cumcm2026.sty` 原样，在 `paper/main.tex` 中进行本地适配。按上述标准检查模板输出，将差异及处理依据记录在 `docs/paper/template-adaptation.md`，并保留其中已确认的本次提交设置。

## 测试与验算要求

回归测试采用标准库 `unittest`。完成数据预处理后执行：

```powershell
python scripts/test_contracts.py
python scripts/test_feedback.py
python scripts/test_external_inputs.py
```

测试文件命名为 `test_*.py`，测试方法以 `test_` 开头。覆盖交易结算、信息可用时点和物理约束；目前未设置覆盖率阈值。

重算后运行 `python scripts/validate_results.py`、`python scripts/validate_revision.py` 和 `python scripts/verify_q1_milp.py`；补充实验另运行 `python scripts/validate_round2.py`。验证 JSON 与对应结果一同保存，计算成功不能代替独立验算通过。

## 提交与 PR 规范

沿用 Git 历史中的 Conventional Commits：`feat:`、`fix:`、`docs(paper):`、`chore:`，主题简短并描述具体动作。PR 应说明变更，关联相关 Issue 或决策文档，列出验算命令；排版或图表变更附渲染预览。不要提交缓存、临时文件或 Office 锁文件。

## 建模与可复现性

在 `docs/modeling/decisions.md` 中记录假设。保持 kW/kWh 单位、十分钟时段对齐和 SOC 连续承接，决策只使用当时已到达的信息。派生文件通过脚本重建。明确区分同年再分析与未见年度验证；可行性验证不代表全局最优。
