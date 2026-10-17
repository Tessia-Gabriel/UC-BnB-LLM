# Phase 0：UC variable-only baseline

## 范围与模型

本阶段把 UC 作为新的 solver evaluator 接入固定版本 LLM4Branch。
研究输入仍是 fractional commitment candidates，程序接口仍是
`score_function(variable_features, params) -> (n_candidates,)`。

`src/ucbranch/uc.py` 实现单母线、确定性需求、热机组 UC：

- 二进制 commitment `u[i,t]`；连续出力 `p[i,t]`。
- 连续 startup/shutdown `v,w`，通过转移等式和上下界，在二进制 u 下
  唯一等于对应 0/1 启停事件，不需要额外整数变量。
- 功率平衡、最小/最大出力、爬坡、最小开机/停机时间。
- 成本为线性发电成本 + 每时段固定开机成本 + 启动成本。
- 所有机组初始关闭且已满足最小停机时间；启动与停机允许达到 pmax。
- 最小开停机约束施加到有限时域内；不施加时域外的终端运行承诺。
- 不包含网络、备用、储能、多段成本或需求响应；这些不是当前 baseline
  的建模内容。每次评估记录完整 instance 数据，后续扩展需重建公平对照。

验收实例固定为 12 台机组、24 时段，seed 0/1/2。搜索训练 seed 12、
验证 seed 16；均为开发数据，未定义或使用正式 Test/OOD。
`validate` 独立重算每个可行调度的功率平衡、出力、爬坡、最小开停机约束和成本。

## 四组 baseline

`src/ucbranch/solver.py` 对四种方法使用同一 UC 模型、SCIP 时间限制 60 秒、
固定随机种子及单线程设置。SCIP default 使用原生 branching；其余方法通过
定制 Ecole 的 Branching 环境接管变量选择，保留相同 solver 参数。

| 方法 | 选择规则 |
|---|---|
| default | SCIP 默认策略 |
| pseudocost | 上游 Ecole Pseudocosts 的最大值 |
| most_fractional | 距离最近整数最远的候选 |
| llm4branch | 上游格式的参数化变量评分函数 |

Ecole 的 action ID 是 SCIP problem index。每个节点重新从 transformed
SCIPgetVars 顺序建立映射，不能使用变量的 creation index。运行时断言所有
候选映射到 `u_i_t`，并保留第一次候选映射作为审计证据。

通用 91 维特征直接复用 NodeBipartiteFlash + Khalil2016Flash；归一化调用
上游 `normalize`。most-fractional 在归一化前读取 fractionality；学习规则
按上游规范使用归一化后的所声明特征。评分必须与候选数一致且全部有限。

## 上游复用和数据契约

- `integration.py` 导入上游 loader/normalizer，保留上游 BO 函数原始代码，
  仅在独立函数绑定中把 `execute_ecole` 替换为 UC task adapter；不修改上游
  模块的全局变量或源文件。BO 仍由原版 skopt Optimizer/ask/tell 实现。
- `evaluator.py` 提供 `evaluate_stage1(path, EvaConfig)`、`evaluate_stage2`
  和 `evaluate`。Stage 1 校验程序声明和输出，Stage 2 执行 BO、UC 求解及
  与 SCIP default 的目标值一致性检查。
- 只有证明 optimal 且与 reference 相符时 `validity=1`；超时或失败不能
  当成正确性通过。`combined_score=log(1+10000/avg_nodes)`，越大越好。
- 保留 `params` 返回契约，上游 worker 自动把 BO 参数写回 child code。
- `scripts/phase0.py` 直接实例化原版 OpenEvolve；搜索主循环、checkpoint、
  provider retry、program database 均调用上游。
- program database 保存源程序、fitness、谱系以及 prompt/response。
  原版 UUID 记录保留；派生 `programs_unique.jsonl` 以 SHA-256 去重并保留所有
  对应 UUID。重复源代码/参数的 solver evaluation 使用内容寻址缓存。
- cache identity 包含完整实例、程序、参数、SCIP/Ecole/PySCIPOpt 版本和
  本地实现源码。原始 solver run 保存状态、目标值、上下界、gap、nodes、
  SCIP 时间、端到端时间、参数、调度和候选映射。

缓存中的时间是首次实际评估时间，不能把缓存读取时间用于性能比较。
Ecole/Python 回调本身存在开销，因此这里验证的是算法接口和 exactness，
还不能据此宣称低开销部署或研究级速度收益。

## 执行与输出

```bash
.conda/llm4branch/bin/python scripts/phase0.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .conda/llm4branch/bin/python -m pytest -q
bash scripts/run_phase0_smoke.sh --output outputs/phase0-final
```

搜索 smoke 使用已有本地 OpenAI-compatible mock。正式模型运行可提供
新的 `--search-config`，连接真实模型并沿用同一 evaluator；本阶段不宣称
已验证真实 LLM 的搜索质量。外部模型代码会被上游 loader 导入执行，需在
隔离环境运行；静态检查不是代码沙箱。

输出目录包含 `baselines.json`、`evaluations/*.json`、`provenance.json`、
`program_database/`、`programs_unique.jsonl`、`search/checkpoints/` 和日志。
模型名称、采样参数和 seed 与锁定上游信息保存在 provenance 中，密钥不写入。

## 正确性验收

验收测试覆盖：小实例 64 种 commitment 的穷举最优值对照；四种策略在
实际发生分支的实例上 objective 一致；非有限评分拒绝；上游种子程序
读取未声明特征的问题被拒绝。

开发 baseline 的目标值分别为 239463.06、241759.38、254895.25；
全部四种方法达到 optimal，误差小于 1e-4。seed 0 的 default、pseudocost、
most-fractional、LLM4Branch-style nodes 分别为 1、11、7、11。
这说明可保持最优性，也说明当前评分规则没有超越 SCIP default 的证据。

最终验收输出为 `outputs/phase0-final/`：12 次 baseline 求解全部通过；
pytest 为 4 passed；两轮 mock-provider OpenEvolve 搜索保存 3 个 program UUID，
对应 2 份不同源代码，全部 validity=1。验证 seed 16 的评分程序使用 69 个
节点。此次搜索执行真实 UC/SCIP 求解、BO 和 cascade，仅模型响应由 mock
提供，因此验收结论限于 Phase 0 接口闭环与求解正确性。

后续 structured branching 应沿用本模型、实例、solver 参数和计时口径，
另设固定训练/验证/Test/OOD 划分与更大预算。Phase -1 审计发现的
prompt-loss-on-resume 仍需在正式数据采集前修复；本次搜索不依赖 resume。
