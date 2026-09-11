# 目录整理与迁移记录

本次只调整文件位置、路径引用和导航，不改变模型、论文内容及原始材料。脚本入口与测试命令保持不变。

实验结果与专项验证放在同一目录；跨产物验收放入 outputs/verification。paper/generated 保留为自动生成的 LaTeX 内容。

| 原路径 | 新路径 |
| --- | --- |
| `docs/decisions.md` | `docs/modeling/decisions.md` |
| `docs/data-audit.md` | `docs/modeling/data-audit.md` |
| `docs/external-validation-protocol.md` | `docs/modeling/external-validation-protocol.md` |
| `docs/template-spec.md` | `docs/modeling/template-spec.md` |
| `docs/model-review.md` | `docs/reviews/model-review.md` |
| `docs/review-response.md` | `docs/reviews/review-response.md` |
| `docs/revision-plan.md` | `docs/reviews/revision-plan.md` |
| `docs/round2-response.md` | `docs/reviews/round2-response.md` |
| `docs/round2-plan.md` | `docs/reviews/round2-plan.md` |
| `docs/template-adaptation.md` | `docs/paper/template-adaptation.md` |
| `docs/table-style-audit.md` | `docs/paper/table-style-audit.md` |
| `docs/equation-style-audit.md` | `docs/paper/equation-style-audit.md` |
| `docs/paper-writing-notes.md` | `docs/paper/paper-writing-notes.md` |
| `docs/paper-revision-teacher.md` | `docs/paper/paper-revision-teacher.md` |
| `docs/literature-notes.md` | `docs/paper/literature-notes.md` |
| `outputs/dispatch.npz` | `outputs/main/dispatch.npz` |
| `outputs/q1-milp-verification.json` | `outputs/main/q1-milp-verification.json` |
| `outputs/reproduction-validation.json` | `outputs/verification/reproduction-validation.json` |
| `outputs/result1.xlsx` | `outputs/deliverables/result1.xlsx` |
| `outputs/result2.xlsx` | `outputs/deliverables/result2.xlsx` |
| `outputs/result3.xlsx` | `outputs/deliverables/result3.xlsx` |
| `outputs/result4-2.xlsx` | `outputs/deliverables/result4-2.xlsx` |
| `outputs/result4-3.xlsx` | `outputs/deliverables/result4-3.xlsx` |
| `outputs/results.json` | `outputs/main/results.json` |
| `outputs/revision-dispatch.npz` | `outputs/experiments/revision/dispatch.npz` |
| `outputs/revision-experiments.json` | `outputs/experiments/revision/experiments.json` |
| `outputs/revision-validation.json` | `outputs/experiments/revision/validation.json` |
| `outputs/summary.json` | `outputs/main/summary.json` |
| `outputs/validation.json` | `outputs/main/validation.json` |
| `outputs/workbook-verification.json` | `outputs/verification/workbook-verification.json` |
| `outputs/paper-study/dispatch.npz` | `outputs/experiments/paper-study/dispatch.npz` |
| `outputs/paper-study/sensitivity.json` | `outputs/experiments/paper-study/sensitivity.json` |
| `outputs/paper-study/validation.json` | `outputs/experiments/paper-study/validation.json` |
| `outputs/pdf/microgrid-paper.pdf` | `outputs/deliverables/microgrid-paper.pdf` |
| `outputs/round2/dispatch.npz` | `outputs/experiments/round2/dispatch.npz` |
| `outputs/round2/experiments.json` | `outputs/experiments/round2/experiments.json` |
| `outputs/round2/interface-smoke.json` | `outputs/experiments/round2/interface-smoke.json` |
| `outputs/round2/validation.json` | `outputs/experiments/round2/validation.json` |
| `paper/validation.json` | `outputs/verification/paper-validation.json` |
| `paper/table-style-validation.json` | `outputs/verification/table-style-validation.json` |

路径变更会使源码审计哈希失效，须重新运行相关计算与验证生成证据，不能直接把旧哈希替换成新哈希冒充重新验算。

## 生成来源与使用约定

- `outputs/main/` 与 `outputs/experiments/revision/` 由 `scripts/solve.py` 生成，对应验证脚本分别为 `validate_results.py`、`validate_revision.py`，问题一另由 `verify_q1_milp.py` 核验。
- `outputs/experiments/round2/` 由 `evaluate_round2.py` 生成，使用 `validate_round2.py` 验算。
- `outputs/experiments/paper-study/` 由 `evaluate_paper_sensitivity.py` 生成，使用 `validate_paper_sensitivity.py` 验算。
- `outputs/deliverables/` 中 Excel 由 `export_results.mjs` 生成，PDF 由 `build_paper.py` 生成；工作簿核验写入 `outputs/verification/`。
- `docs/solution.md` 与第二轮回应中的结果区块由 `build_report.py` 更新，修改生成内容时应同步修改脚本。
- `paper/generated/` 是生成内容，继续跟随论文源码保存；上游模板、题面和原始数据保持原样。
- `outputs/verification/reproduction-validation.json` 与 `outputs/experiments/round2/interface-smoke.json` 保留历史验收含义；前者的旧路径和源码哈希属于迁移前版本，不能当作当前源码的重新验收。

## 迁移验收

验收明细见[结构迁移验证](../outputs/verification/structure-validation.json)。本次重新计算主策略和补充实验，再运行对应的独立验证；比较迁移前后的 JSON 数值和 NPZ 数组，忽略运行耗时及来源路径/哈希元数据。五个 Excel 保持字节一致。论文重新编译，逐页比较渲染结果，并人工检查路径发生变化的末页。

脚本入口与命令保持原样，旧输出路径不再保留兼容副本，避免生成两套结果。
