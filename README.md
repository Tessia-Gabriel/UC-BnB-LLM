# UC branching research

第一次接触 UC 或 LLM？请先读
[新手说明：LLM4Branch、我们的目标与当前困境](docs/BEGINNER_GUIDE_ZH.md)。
不需要数学优化或大模型基础，包含例子、实验结果和下一步排查思路。

进一步看 [完整架构与大规模研究路线](docs/ARCHITECTURE_AND_SCALE_ZH.md)：
明确各层职责、已接通与未实现的功能、临时方案代价，以及后续实验决策方式。
`scripts/scale_probe.py` 默认只展示可配置的大规模检查计划，加入 `--run` 才求解。

公开 UC 数据与“默认 SCIP / LLM4Branch 公开程序”的白话区别见
[公开实例与公开规则说明](docs/PUBLIC_UC_AND_LLM4BRANCH_ZH.md)。
已经冻结的数据划分、官方模型双向对账和第一次六方法试跑见
[公开 UC 执行记录](docs/PUBLIC_UC_EXECUTION_ZH.md)。
500 台以下、使用官方模型直接导出 MPS 的自适应实验见
[500 台以下官方 MPS 实验结果](docs/UNDER500_OFFICIAL_MPS_RESULTS_ZH.md)。
用 `.conda/llm4branch/bin/python scripts/public_uc.py --limit 60` 可运行默认的
OR-LIB 200 台、24 小时实例。

项目目标、阶段边界见 [PROJECT_SPEC.md](PROJECT_SPEC.md) 与技术路线。
Phase 0 已实现单节点热机组 UC、四组 variable-only baseline，以及原版
LLM4Branch/OpenEvolve 的 UC evaluator 和 BO 接口。

在 Phase -1 环境中运行：

```bash
.conda/llm4branch/bin/python scripts/phase0.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .conda/llm4branch/bin/python -m pytest -q
bash scripts/run_phase0_smoke.sh --output outputs/phase0-new-run
```

最后一条命令启动本地 mock provider，执行真实 UC/SCIP 搜索、BO 和数据库导出。
每次搜索使用新的输出目录。更多建模假设、验收结果及复用边界见
[docs/PHASE0.md](docs/PHASE0.md)。

Phase 1 的四类 structured branching DSL、SCIP 编译与回退见
[docs/PHASE1.md](docs/PHASE1.md)。运行 `.conda/llm4branch/bin/python scripts/phase1.py`
生成正确性验收记录；本阶段不代表通过 Phase 2 的性能收益门禁。

Phase 2 的 30 实例人工规则实验见 [docs/PHASE2.md](docs/PHASE2.md)。
运行 `.conda/llm4branch/bin/python scripts/phase2.py --output outputs/phase2-run-v2`；
使用固定协议可恢复，修改预算或源码后须使用新输出目录。是否通过 Gate 1
由实验结果判定，不预设结构分支一定优于 SCIP。
