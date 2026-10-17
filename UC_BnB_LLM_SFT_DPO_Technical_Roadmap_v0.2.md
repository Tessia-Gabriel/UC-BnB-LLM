# UC + Branch-and-Bound + Solver-Feedback LLM Post-Training
## 技术执行文档 v0.2：基于 LLM4Branch / OpenEvolve 的复用式开发路线

> **核心原则：不重复造轮子。**  
> 现有 LLM4Branch / OpenEvolve 已经解决的通用工程问题——程序进化搜索、LLM 调用、候选数据库、checkpoint、并行评估、级联筛选、参数优化——尽量直接复用。  
> 本项目只开发真正构成研究创新的部分：**UC 结构化 branching search space、UC-specific features、structured disjunction compiler、solver-feedback SFT/DPO，以及最终冻结的低开销 branching rule / portfolio。**

---

# 0. 最终研究目标

本项目不训练一个“在线替 SCIP 决策的大模型”。

最终目标是：

> **利用 LLM4Branch / OpenEvolve 作为离线自动算法搜索底座，通过 solver feedback 对开源 LLM 进行 SFT + DPO 后训练，使其更擅长发现面向 Unit Commitment（UC）时空结构的 branching heuristics；最终只部署冻结后的轻量规则，不在线调用 LLM。**

最终产出分两层。

## 0.1 最终算法产出

一个或一组确定性的 UC branching algorithms：

```text
UC instance
    ↓
SCIP Branch-and-Bound
    ↓
cheap deterministic features
    ↓
frozen branching rule / portfolio selector
    ↓
branching decision
```

在线满足：

\[
\boxed{\text{LLM calls}=0}
\]

最终关注：

- solve time；
- node count；
- primal-dual integral；
- solved rate；
- timeout rate；
- Test / OOD 泛化。

## 0.2 LLM 方法产出

一个经过后训练的离线 heuristic designer：

\[
\text{Base Open-Source LLM}
\rightarrow
\text{SFT}
\rightarrow
\text{DPO}
\]

用于：

- 生成 branching program；
- 修改已有 program；
- 组合 elite program；
- 解释失败模式并提出新的程序结构。

它只存在于 **offline algorithm discovery** 中。

---

# 1. 与 LLM4Branch 的研究边界

这是整个项目必须长期保持清晰的一条边界。

## 1.1 LLM4Branch 风格的核心问题

输入：

\[
\{x_1,x_2,\ldots,x_m\}_{\text{fractional candidates}}
\]

通过 LLM 自动发现一个变量评分函数：

\[
s_i=f(\phi_i;\theta)
\]

然后：

\[
i^\star=\arg\max_i s_i.
\]

研究问题本质上是：

> **Which existing branching variable should be selected?**

我们将它作为强 baseline 和基础设施来源，而不是重新实现同一研究问题。

---

## 1.2 本项目的核心问题

我们允许 branching object 不再局限于单个 binary variable。

候选对象包括：

```text
VAR
UNIT_ON_COUNT
START_COUNT
GROUP_ON_COUNT
BLOCK_ON_COUNT
```

研究问题变成：

> **What UC structural object should the solver branch on, and under what state should each type be used?**

即：

\[
\boxed{
\text{Variable Scoring}
\rightarrow
\text{UC-Structured Branching Program Discovery}
}
\]

---

# 2. 复用 / 修改 / 自研边界

开发前必须明确哪些模块不值得重写。

| 模块 | 处理方式 | 备注 |
|---|---|---|
| OpenEvolve 主循环 | **直接复用** | population / iteration / mutation / elite |
| program database | **直接复用** | 后续直接转 SFT / DPO 数据 |
| checkpoint / resume | **直接复用** | 不自己重写 |
| LLM async / retry / ensemble | **直接复用并适配本地模型** | 后期接 vLLM |
| cascade evaluation 调度 | **复用框架，替换 evaluator** | Cheap → Medium → Full |
| program mutation / crossover prompt | **复用并改 prompt** | 加 UC DSL |
| Bayesian / zeroth-order parameter tuning | **尽量复用** | LLM 找结构，BO 找数值 |
| 通用 MILP variable features | **复用为 baseline 特征** | 不重新造几十个通用特征 |
| LLM4Branch variable score function | **仅保留为 baseline** | 不作为我们的主方法 |
| UC instance generator | **自研** | 领域相关 |
| UC structural features | **自研** | 核心贡献 |
| structured branching DSL | **自研** | 核心贡献 |
| generalized disjunction compiler | **自研** | 核心贡献 |
| structured branch oracle | **自研 / 改 evaluator** | 用 SCIP feedback |
| SFT dataset builder | **自研** | program DB → demonstrations |
| DPO dataset builder | **自研** | program DB → preferences |
| QLoRA SFT / DPO | **自研训练流程** | 使用成熟 HF / TRL 工具 |
| final rule portfolio | **自研** | 在线无 LLM |

---

# 3. 总体系统架构

## 3.1 Round-0：不微调，先用现成搜索框架采真实数据

```text
Base LLM
   ↓
LLM4Branch / OpenEvolve
   ↓
UC structured program search
   ↓
SCIP cascade evaluator
   ↓
program database
   ↓
真实 solver-validated programs
```

这一轮的目标不是得到最终算法，而是：

1. 验证 search space；
2. 建立 baseline；
3. 自动产生 SFT / DPO 原始数据。

---

## 3.2 后训练

```text
OpenEvolve program database
          │
    ┌─────┴─────┐
    ↓           ↓
Top programs   Ranked program pairs
    ↓           ↓
SFT dataset    DPO dataset
    ↓           ↓
QLoRA SFT      DPO
    └─────┬─────┘
          ↓
Fine-tuned heuristic designer
```

---

## 3.3 Round-1：后训练模型重新参与算法发现

```text
Fine-tuned LLM
      ↓
OpenEvolve
      ↓
new structured branching programs
      ↓
same SCIP evaluator
      ↓
compare search efficiency / final rule quality
```

---

## 3.4 最终部署

```text
Elite program(s)
      ↓
HPO / BO final tuning
      ↓
Validation selection
      ↓
FREEZE
      ↓
Test / OOD
```

此后关闭 LLM。

---

# 4. 建议代码组织

不要把 LLM4Branch 的代码复制散落到项目中。

推荐：

```text
uc-structured-branching/
├── README.md
├── PROJECT_SPEC.md
├── pyproject.toml
├── third_party/
│   └── llm4branch/
│       └── ... pinned upstream code ...
├── configs/
│   ├── openevolve/
│   ├── scip/
│   ├── uc/
│   ├── search/
│   ├── sft/
│   └── dpo/
├── src/
│   └── ucbranch/
│       ├── integration/
│       │   ├── llm4branch_adapter.py
│       │   ├── openevolve_adapter.py
│       │   └── evaluator_adapter.py
│       ├── uc/
│       │   ├── instance.py
│       │   ├── generator.py
│       │   ├── scip_model.py
│       │   └── validator.py
│       ├── features/
│       │   ├── generic_adapter.py
│       │   ├── uc_static.py
│       │   ├── uc_node.py
│       │   └── structural.py
│       ├── branching/
│       │   ├── dsl.py
│       │   ├── candidate_builder.py
│       │   ├── compiler.py
│       │   ├── safety.py
│       │   ├── variable.py
│       │   ├── unit_window.py
│       │   ├── start_count.py
│       │   ├── group_count.py
│       │   └── block_count.py
│       ├── evaluation/
│       │   ├── cheap_filter.py
│       │   ├── medium_eval.py
│       │   ├── full_eval.py
│       │   ├── strong_eval.py
│       │   └── fitness.py
│       ├── datasets/
│       │   ├── export_program_db.py
│       │   ├── build_sft.py
│       │   ├── build_dpo.py
│       │   └── split.py
│       ├── training/
│       │   ├── sft_train.py
│       │   ├── dpo_train.py
│       │   └── eval_designer.py
│       ├── serving/
│       │   ├── vllm_server.sh
│       │   └── client.py
│       └── final/
│           ├── freeze_rule.py
│           ├── portfolio.py
│           └── final_eval.py
├── scripts/
└── outputs/
```

要求：

- `third_party/llm4branch` 固定 commit；
- 保留原始 license / attribution；
- 我们的修改尽量通过 adapter 完成；
- 避免 fork 后大规模魔改上游核心。

---

# 5. Branching DSL v1

LLM 不直接生成任意 SCIP 操作，而是生成受限 program。

## 5.1 VARIABLE_BRANCH

```text
VAR(unit=i, time=t)
```

对应：

\[
u_{i,t}=0
\quad\vee\quad
u_{i,t}=1.
\]

这是 LLM4Branch-style baseline 的主要对象。

---

## 5.2 UNIT_ON_COUNT

```text
UNIT_ON_COUNT(unit=i, start=t_1, end=t_2)
```

定义：

\[
s=\sum_{t=t_1}^{t_2}u_{i,t}.
\]

若当前 LP：

\[
s^\star\notin\mathbb Z,
\]

则创建：

\[
s\le\lfloor s^\star\rfloor
\quad\vee\quad
s\ge\lceil s^\star\rceil.
\]

---

## 5.3 START_COUNT

```text
START_COUNT(unit=i, start=t_1, end=t_2)
```

定义：

\[
s=\sum_{t=t_1}^{t_2}y_{i,t}.
\]

用于刻画一个时间窗口内的启动事件。

---

## 5.4 GROUP_ON_COUNT

```text
GROUP_ON_COUNT(group=g, time=t)
```

定义：

\[
s=\sum_{i\in\mathcal G_g}u_{i,t}.
\]

第一版 group：

- FAST
- SLOW
- BASELOAD
- PEAKER
- HIGH_START_COST
- LOW_START_COST

---

## 5.5 BLOCK_ON_COUNT

```text
BLOCK_ON_COUNT(group=g, start=t_1, end=t_2)
```

定义：

\[
s=
\sum_{i\in\mathcal G_g}
\sum_{t=t_1}^{t_2}u_{i,t}.
\]

v1 不开放任意 \(\pi^\top x\)，避免搜索空间失控。

---

# 6. Program Skeleton 与参数分离

这一点直接继承 LLM4Branch 的重要思想。

候选 heuristic 表示为：

\[
\pi=(P,\theta)
\]

其中：

- \(P\)：LLM 负责发现的程序结构；
- \(\theta\)：BO / HPO 负责优化的数值参数。

LLM 不应浪费能力去猜：

```text
0.372
0.418
1.27
```

而应该决定：

- 哪些特征值得使用；
- 哪种 branch object 值得选择；
- 什么条件下切换；
- 哪种 fallback 合理；
- 特征之间如何组合。

示例：

```python
def branching_rule(state, candidates, params):
    if (
        state.temporal_fractionality
        > params["temporal_threshold"]
        and state.ramp_tightness
        > params["ramp_threshold"]
    ):
        return choose_unit_window(
            candidates,
            temporal_weight=params["w_temporal"],
            ramp_weight=params["w_ramp"],
        )

    return choose_variable_by_pseudocost(
        candidates,
        weight=params["w_pc"],
    )
```

然后：

\[
\theta^\star(P)
=
\arg\min_\theta F(P,\theta).
\]

---

# 7. 特征体系

统一：

\[
\phi(s)=
[
\phi_{\text{generic}},
\phi_{\text{UC}}
].
\]

## 7.1 Generic MILP features

优先复用 LLM4Branch / 现有 feature extractor 提供的通用变量 / LP 特征，不重复实现。

例如：

- fractionality；
- pseudocost；
- reduced cost；
- constraint activity；
- objective coefficient；
- graph / degree statistics；
- variable type；
- LP solution value。

如果上游某特征提取模块无法直接适配 PySCIPOpt，则只写 thin adapter。

---

## 7.2 UC static features

新增：

- capacity_tightness；
- ramp_tightness；
- startup_cost_ratio；
- marginal_cost_cv；
- capacity_cv；
- ramp_cv；
- min_up_avg；
- min_down_avg；
- fast_unit_ratio；
- baseload_ratio；
- peaker_ratio；
- peak_load_ratio。

---

## 7.3 UC node / structural features

新增：

- temporal_fractionality；
- startup_fractionality；
- startup_ambiguity；
- neighboring_commitment_fractionality；
- min_up_down_conflict_score；
- ramp_conflict_score；
- peak_period_importance；
- group_ambiguity；
- window_fractionality；
- fractionality concentration by time；
- fractionality concentration by unit。

---

# 8. Phase -1：原样复现 LLM4Branch / OpenEvolve

**此阶段不写我们自己的算法。**

目标：

> 先确认上游搜索框架、program database、evaluator、checkpoint、参数优化和 LLM 接口全部跑通。

任务：

1. clone / fork 官方项目；
2. pin 一个固定 commit；
3. 建立独立 Python 环境；
4. 原样运行一个官方 benchmark；
5. 找到并理解：
   - initial program；
   - program representation；
   - evaluator interface；
   - program database；
   - cascade evaluator；
   - parameter optimization；
   - checkpoint / resume；
   - LLM provider interface；
6. 记录最小运行命令；
7. 不修改核心代码。

验收：

- 可以完整完成至少一个短搜索；
- 可以中断并 resume；
- 可以导出所有 evaluated programs；
- 可以读取每个 program 的 fitness 和参数；
- 明确 evaluator 与 OpenEvolve 之间的数据契约。

**Gate -1：如果上游都没有跑通，不进入 UC 改造。**

---

# 9. Phase 0：UC Variable-Only LLM4Branch Baseline

目标：

> 先把 LLM4Branch 原思路移到 UC，得到完全公平的直接 baseline。

此阶段只允许：

```text
VARIABLE_BRANCH
```

仍然研究：

\[
\text{Which fractional }u_{i,t}\text{ should be branched on?}
\]

任务：

1. 将 UC MILP 接入 SCIP；
2. 将 UC fractional binary variables 映射到上游 candidate format；
3. generic feature extractor 接入；
4. evaluator 改成 UC solver；
5. 使用相同 OpenEvolve 搜索逻辑；
6. 保留 BO / parameter tuning；
7. 运行：
   - SCIP default；
   - pseudocost；
   - most fractional；
   - LLM4Branch-style variable scorer。

输出：

- UC variable-only baseline；
- program database；
- solver metrics；
- 后续对 structured search 的公平基准。

**Gate 0：必须保证最终 objective / exactness 与标准 SCIP 一致。**

---

# 10. Phase 1：最小 Structured Branching DSL

这才是我们的第一个核心开发阶段。

目标：

> 在不引入 LLM 后训练之前，证明新的 branching object 本身有价值。

先实现：

1. `VAR`
2. `UNIT_ON_COUNT`
3. `START_COUNT`
4. `GROUP_ON_COUNT`

`BLOCK_ON_COUNT` 暂缓。

每种对象包括：

- candidate generation；
- LP value 计算；
- branch validity check；
- SCIP child creation；
- fallback；
- unit tests。

统一接口：

```python
@dataclass(frozen=True)
class BranchCandidate:
    kind: str
    params: dict
    lp_value: float
    features: dict[str, float]

@dataclass(frozen=True)
class BranchDecision:
    kind: str
    params: dict
    score: float
```

---

# 11. Phase 2：人工 Structured Branching 可行性实验

完全不使用 LLM。

设计若干简单规则：

```python
if startup_ambiguity > theta1:
    return best_start_count()

if temporal_fractionality > theta2:
    return best_unit_window()

return pseudocost_variable()
```

实验规模：

- 30–50 UC instances；
- 10 / 20 / 50 units；
- 多种 ramp / startup / peak 场景。

比较：

- SCIP default；
- pseudocost；
- variable-only LLM4Branch baseline；
- handcrafted structured rule。

指标：

- solve time；
- node count；
- primal-dual integral；
- time to first incumbent；
- final gap；
- solved rate。

**Gate 1：必须至少在一类实例 / tree 状态看到 structured branch 的明确收益。**

如果没有：

- 不进入 SFT；
- 优先修改 DSL；
- 调整 window / group 构造；
- 限制 structured branch 只在浅层节点；
- 加强 hybrid fallback。

---

# 12. Phase 3：Structured Candidate Builder + Oracle

目标：

> 让 evaluator 能系统比较不同 branching object。

候选池：

```text
fractional VAR candidates
+
top temporal UNIT_ON_COUNT candidates
+
top START_COUNT candidates
+
top GROUP_ON_COUNT candidates
```

控制：

\[
K\le 20\sim50.
\]

---

## 12.1 Cheap strong-style score

对候选左右分支进行有限 LP 评价：

\[
Q_{\text{SB}}(a)
=
\min(\Delta LB_L,\Delta LB_R)
+
\gamma
\max(\Delta LB_L,\Delta LB_R).
\]

---

## 12.2 Short rollout

仅 top candidates 进一步运行固定：

- node budget；
- time budget。

记录：

- bound improvement；
- nodes；
- local primal improvement；
- PD integral。

---

## 12.3 不自己实现大规模调度框架

将上述 oracle 封装进 **LLM4Branch/OpenEvolve evaluator contract**。

不要新写另一套：

- worker manager；
- checkpoint；
- task queue；
- resume system。

---

# 13. Phase 4：接入 OpenEvolve Cascade Evaluator

将我们原先计划的 Cheap / Medium / Full 统一放到上游 cascade 框架。

推荐：

## Level 0：Static Filter

- AST / syntax；
- DSL safety；
- banned operation；
- runtime guard；
- interface validation。

## Level 1：Cheap

- 3–5 small UC instances；
- strict timeout；
- catastrophic slowdown 淘汰。

## Level 2：Medium

- 20–30 train instances；
- node / time / PD integral。

## Level 3：Full

- 100–200 train / validation instances；
- 仅 elite programs。

每一级只保留：

\[
20\%\sim40\%
\]

进入下一级。

---

# 14. Phase 5：Round-0 Algorithm Search

此阶段仍然 **不微调模型**。

目的：

1. 检验 Base LLM + OpenEvolve 能否在 structured DSL 中发现有效规则；
2. 获取真实 solver-validated program corpus；
3. 为 SFT / DPO 自动生产数据。

初始 population：

- handcrafted structured rules；
- UC-adapted variable scorers；
- simple hybrids。

Base LLM 负责：

- mutation；
- feature组合；
- branch type切换逻辑；
- fallback设计；
- crossover。

BO 负责：

- threshold；
- weight；
- depth cutoff；
- branch-type参数。

推荐搜索：

- 10–20 generations；
- 每代 50–100 programs；
- 先控制总 unique programs 在 1k–3k。

输出的关键文件：

```text
program_id
parent_id
generation
prompt_id
program_code
parameter_vector
validation_status
cheap_fitness
medium_fitness
full_fitness
instance_family_metrics
```

---

# 15. Phase 6：直接从 Program Database 构建 SFT 数据

**不再先人工造 5k 条 SFT。**

SFT 数据优先来自 Round-0 的真实优秀程序。

## 15.1 数据来源优先级

1. Full evaluator elite programs；
2. Medium evaluator 高质量 programs；
3. handcrafted seed；
4. 少量高质量人工补充。

不要把大量未验证 LLM 代码塞进 SFT。

---

## 15.2 SFT prompt

输入包含：

- UC problem description；
- allowed features；
- allowed DSL；
- program interface；
- observed failure pattern；
- parent / baseline summary。

输出：

```text
DESIGN:
1–3 sentence design summary.

CODE:
deterministic branching program.
```

不要求长 chain-of-thought。

---

## 15.3 SFT 样本数量

第一版：

\[
1k\sim3k
\]

真实高质量 examples 就可以先训练。

正式版再扩大：

\[
3k\sim10k.
\]

与旧方案相比：

> **宁可数据少，也优先使用 solver-validated programs。**

---

# 16. Phase 7：QLoRA SFT

推荐模型梯度：

- 3B：pipeline debug；
- 7B：主模型；
- 14B：可选 scaling experiment。

主方案：

```text
7B instruct/code model
+
4-bit quantization
+
LoRA / QLoRA
```

初始配置：

```yaml
lora:
  r: 32
  alpha: 64
  dropout: 0.05

training:
  epochs: 2
  learning_rate: 2e-4
  max_seq_length: 4096
```

实际根据显存调整。

---

## 16.1 SFT 评估

不要只看 validation loss。

比较 Base vs SFT：

- syntax validity；
- DSL validity；
- safety pass；
- SCIP runnable；
- unique rule ratio；
- structured branch usage diversity；
- cheap evaluator pass rate；
- medium fitness；
- best-of-N fitness。

核心问题：

> SFT 是否让模型更容易生成“值得进入 solver evaluator”的规则？

---

# 17. Phase 8：从 Program Database 构建 DPO 数据

同样不要单独造 preference。

Round-0 和 SFT-model generation 自然产生大量：

\[
(\text{program}, \text{fitness})
\]

数据。

---

## 17.1 Pair 原则

同一个 / 高度相近 prompt 下比较：

\[
\pi_a,\pi_b.
\]

如果：

\[
F(\pi_a) < F(\pi_b)
\]

且差距超过 margin：

\[
\frac{F(\pi_b)-F(\pi_a)}
{|F(\pi_a)|+\epsilon}
>\delta,
\]

则：

```text
chosen   = pi_a
rejected = pi_b
```

推荐：

\[
\delta=5\%\sim10\%.
\]

---

## 17.2 Fitness

统一 evaluator：

\[
F(\pi)
=
w_t T_{\text{norm}}
+
w_n N_{\text{nodes,norm}}
+
w_p I_{\text{PD}}
+
w_o P_{\text{timeout}}.
\]

重要：

- pair 必须在相同 instance set 上评价；
- runtime 用 median / geometric mean；
- timeout 要有明确 penalty；
- 接近的规则不强行构造 preference。

---

## 17.3 DPO 数据规模

MVP：

\[
5k\sim10k
\]

pairs。

正式：

\[
10k\sim30k
\]

高质量 pairs 即可先做。

不强求 50k+。

---

# 18. Phase 9：DPO

在 SFT checkpoint 上继续 DPO。

推荐初值：

```yaml
epochs: 1
learning_rate: 5e-6
beta: 0.1
max_length: 4096
```

比较：

```text
Base
vs
SFT
vs
SFT + DPO
```

评价重点：

- best-of-N solver fitness；
- top-10% generated program quality；
- catastrophic rule rate；
- diversity；
- search sample efficiency。

---

# 19. Phase 10：本地 vLLM 部署

vLLM 不用于在线 B&B。

它只是 OpenEvolve 的本地 LLM backend。

```text
OpenEvolve
    ↓
OpenAI-compatible client
    ↓
local vLLM server
    ↓
fine-tuned heuristic designer
```

必须记录：

- exact checkpoint；
- LoRA adapter；
- decoding config；
- temperature；
- top-p；
- seed；
- token usage；
- prompt hash。

这样能够把昂贵 API 替换为自己的 GPU 服务。

---

# 20. Phase 11：Round-1 Algorithm Search

使用与 Round-0 **相同搜索预算** 比较：

```text
Base LLM + OpenEvolve
vs
SFT LLM + OpenEvolve
vs
SFT+DPO LLM + OpenEvolve
```

要求严格控制：

- generations；
- programs per generation；
- evaluator budgets；
- HPO evaluations；
- train instance set；
- wall-clock budget（额外报告）。

主要研究问题：

### RQ1

SFT 是否提高有效候选率？

### RQ2

DPO 是否提高高质量候选密度？

### RQ3

后训练是否减少达到某个 solver fitness 所需的 candidate evaluations？

### RQ4

后训练模型是否找到更好的最终 branching program？

---

# 21. Phase 12：Final Parameter Optimization

对 Round-1 得到的 top programs 进行更充分 BO / HPO。

不要继续让 LLM 猜数字。

对每个 program structure：

\[
P_j
\]

求：

\[
\theta_j^\star
=
\arg\min_\theta
F(P_j,\theta).
\]

然后只用 Validation 排名。

---

# 22. Phase 13：Rule Portfolio

如果单个规则不能覆盖全部 UC family，允许：

\[
\Pi=
\{\pi_1,\pi_2,\ldots,\pi_K\}.
\]

建议：

\[
K=2\sim4.
\]

selector 必须便宜：

- decision tree；
- rule table；
- logistic regression；
- small classifier。

输入只用 instance-level / cheap initial solver features。

**禁止在线 LLM selector。**

---

# 23. Phase 14：FREEZE

最终导出：

```text
final/
├── rule_1.py
├── rule_2.py
├── selector.py
├── tuned_params.yaml
└── metadata.json
```

metadata：

- upstream LLM4Branch commit；
- OpenEvolve config；
- base model；
- SFT checkpoint；
- DPO checkpoint；
- search budget；
- generation；
- program hash；
- validation score；
- parameter-search config。

从此以后：

> Test / OOD 只评价，不再修改算法。

---

# 24. 数据划分

实例按 **family** 隔离，而不是随机扰动后打散。

推荐第一版：

```text
Train       250–300
Validation   60–80
Test        120–150
OOD          50–70
```

总计：

\[
480\sim600
\]

即可。

---

## 24.1 Train

覆盖：

- 10 / 20 / 50 units；
- moderate capacity；
- moderate / tight ramp；
- startup cost variations；
- diverse load shapes。

## 24.2 Validation

不同基础 generator templates / load profiles。

## 24.3 Test

基础 family 从未参与 program search / SFT / DPO。

## 24.4 OOD

例如：

- 75 / 100 units；
- 48 periods；
- extreme peak；
- extreme ramp；
- extreme capacity tightness。

---

# 25. 必须保留的 Baselines

## 25.1 Classical

- SCIP default；
- most fractional；
- pseudocost；
- reliability branching；
- strong branching（小规模）。

## 25.2 LLM4Branch-style

在我们自己的 UC dataset 上跑：

> **variable-scoring program discovery**

与 structured method 共享：

- solver；
- data split；
- OpenEvolve budget；
- evaluator；
- BO budget。

这是最重要的公平 baseline。

## 25.3 Our Search Space Baselines

- handcrafted structured；
- random program search；
- genetic/evolutionary search without LLM；
- Base LLM + structured DSL；
- SFT + structured DSL；
- SFT+DPO + structured DSL。

---

# 26. 关键消融

## A. Search Space 贡献

```text
LLM4Branch-style variable-only
vs
Our structured DSL + Base LLM
```

若后者更强，说明：

> structured branching space 本身有价值。

---

## B. UC-specific features

```text
generic MILP features
vs
generic + UC structural features
```

---

## C. Post-training

```text
Base
vs
SFT
vs
SFT+DPO
```

---

## D. Solver Feedback

```text
LLM self-ranking
vs
solver-based ranking
```

---

## E. Parameter separation

```text
LLM generates structure + numbers
vs
LLM structure + BO numbers
```

---

## F. Branch Types

删除：

- UNIT_ON_COUNT；
- START_COUNT；
- GROUP_ON_COUNT；
- BLOCK_ON_COUNT。

---

## G. Single vs Portfolio

```text
best single
vs
portfolio
```

---

# 27. 推荐 Fitness 设计

不要让 single runtime 决定一切。

推荐：

\[
F(\pi)
=
w_t\hat T
+
w_n\hat N
+
w_pI_{\mathrm{PD}}
+
w_oP_{\mathrm{timeout}}.
\]

同时保存原始指标。

正式论文至少报告：

- shifted geometric mean solve time；
- node count；
- primal-dual integral；
- solved rate；
- timeout count。

Program evolution 可以使用复合 fitness，但论文不要只报告复合分数。

---

# 28. Program Database 同时承担三个职责

不要额外建立重复数据库。

上游 program DB 应成为单一事实来源。

## 28.1 Algorithm Search

保存 population / lineage / elite。

## 28.2 SFT Export

筛：

```text
valid
+
high fitness
+
diverse
```

导出 demonstrations。

## 28.3 DPO Export

按：

```text
same prompt / parent context
+
significant fitness margin
```

导出 preference pairs。

---

# 29. 推荐数据规模

## Round-0

先控制：

\[
1k\sim3k
\]

unique evaluated programs。

## SFT

第一轮：

\[
1k\sim3k
\]

solver-validated examples。

正式：

\[
3k\sim10k.
\]

## DPO

第一轮：

\[
5k\sim10k
\]

pairs。

正式：

\[
10k\sim30k.
\]

## Round-1

再生成：

\[
2k\sim5k
\]

programs。

总计大约：

\[
3k\sim8k
\]

高价值 unique program evaluations。

具体数量以 SCIP evaluation 成本为准，不为了“数据量好看”强行扩大。

---

# 30. 计算资源优先级

成本排序预计：

```text
Full SCIP evaluation
>
Medium SCIP evaluation
>
LLM generation
>
SFT / DPO training
```

所以优化重点应是 evaluator，而不是过度压缩模型训练。

优先做：

1. cascade；
2. asynchronous workers；
3. early stopping；
4. family subset；
5. result cache；
6. program hash 去重；
7. HPO cache；
8. deterministic rerun。

---

# 31. 阶段门禁

## Gate -1：上游框架复现成功

OpenEvolve / LLM4Branch 能完整搜索和 resume。

## Gate 0：UC variable-only baseline 成功

LLM4Branch-style baseline 可以在 UC 上公平运行。

## Gate 1：structured branching 有真实增益

否则不做后训练。

## Gate 2：OpenEvolve 能稳定搜索 structured DSL

不是大量非法代码或 catastrophic programs。

## Gate 3：Round-0 数据质量足够

存在：

- elite；
- clearly bad programs；
- 稳定 ranking；
- 足够 preference margin。

## Gate 4：SFT 有效

valid / runnable / medium-pass rate 上升。

## Gate 5：DPO 有效

best-of-N / top-decile solver fitness 上升。

## Gate 6：Round-1 搜索效率提升

同预算下优于 Base LLM。

## Gate 7：Final rule 在 Test / OOD 保持收益

且在线没有 LLM inference overhead。

---

# 32. 风险与降级路线

## 风险 1：structured branch 没有优势

降级为：

> UC-specific variable scoring + solver-feedback post-training。

这时论文创新性下降，但可以保留后训练主线。

---

## 风险 2：Generalized branch LP 开销过高

处理：

- 只浅层使用；
- shorter windows；
- sparse groups；
- aggressive fallback；
- 用 structured rule 只决定 candidate subset，再 ordinary branch。

---

## 风险 3：SFT 数据太少

不要用未验证垃圾数据填充。

优先：

- 多 Round-0 seeds；
- program mutation；
- elite neighborhood perturbation；
- diversity sampling。

---

## 风险 4：DPO 不稳定

优先检查：

- pair margin；
- runtime noise；
- context mismatch；
- same-prompt constraint；
- evaluator variance。

必要时先停在 SFT，论文也可以成立。

---

# 33. 新的推荐时间表

## Week 1

**复现，不开发创新：**

- clone / pin LLM4Branch；
- 跑原 benchmark；
- 理清 OpenEvolve 接口；
- 导出 program DB。

## Week 2

**UC variable-only baseline：**

- SCIP UC；
- variable feature adapter；
- evaluator adapter；
- LLM4Branch-style UC baseline。

## Week 3–4

**Structured DSL：**

- UNIT_ON_COUNT；
- START_COUNT；
- GROUP_ON_COUNT；
- handcrafted feasibility tests。

## Week 5

**Structured evaluator：**

- candidate builder；
- strong-style evaluation；
- cascade integration。

## Week 6–7

**Round-0：**

- Base LLM + OpenEvolve；
- 1k–3k program evaluations；
- program database analysis。

## Week 8

**SFT dataset export：**

- elite filtering；
- diversity filtering；
- prompt reconstruction。

## Week 9

**QLoRA SFT：**

- 3B smoke test；
- 7B main training；
- generation evaluation。

## Week 10

**DPO dataset：**

- pair builder；
- margin analysis；
- noise filtering。

## Week 11

**DPO：**

- training；
- Base / SFT / DPO generation benchmark。

## Week 12–13

**Round-1：**

- equal-budget algorithm search；
- compare search efficiency。

## Week 14

**BO final tuning + portfolio。**

## Week 15–16

**Freeze + Test / OOD + ablations。**

---

# 34. Codex 开发约束

Codex 必须遵守：

1. 优先调用 / adapter 上游代码，不复制实现。
2. 未证明上游缺少功能前，不新写同类模块。
3. 修改 third-party 必须最小化并记录 patch。
4. 每个 structured branch type 必须独立 unit test。
5. 所有 program 必须 hash 去重。
6. 所有 evaluation 必须 cache。
7. Test / OOD 绝不进入 program search。
8. Program DB 是唯一主数据源。
9. 所有 LLM generation 保存 prompt / model / seed / config。
10. 所有 solver run 保存 SCIP version / params / time limit。
11. SFT / DPO export 必须能追溯到原 program IDs。
12. 最终 rule 必须能脱离 LLM 单独运行。

---

# 35. 当前第一条 Codex 任务

```text
阅读 PROJECT_SPEC.md。

本项目明确以 LLM4Branch / OpenEvolve 为基础设施，
不要重新实现 program evolution、program database、
checkpoint、LLM retry、cascade orchestration 或 parameter optimizer。

当前只完成 Phase -1：

1. 将官方 LLM4Branch 仓库作为 third_party dependency / fork；
2. 固定 commit；
3. 建立可复现环境；
4. 原样运行一个官方最小 benchmark；
5. 找出并文档化：
   - initial program interface
   - evaluator interface
   - program database schema
   - cascade evaluation flow
   - parameter optimization flow
   - checkpoint/resume
   - LLM provider interface
6. 写 docs/LLM4BRANCH_INTEGRATION.md；
7. 不修改任何 UC 代码；
8. 不实现 structured branching；
9. 不实现 SFT/DPO。

完成后汇报：
- upstream commit
- environment
- run command
- critical modules
- reusable interfaces
- unavoidable modifications
- test result
- remaining blockers
```

---

# 36. 第二条 Codex 任务（Phase -1 通过后）

```text
基于已经跑通的 LLM4Branch / OpenEvolve，
实现 UC variable-only baseline。

要求：

1. 不修改 OpenEvolve 搜索主循环；
2. 新建 ucbranch integration adapter；
3. 将 UC fractional commitment variables 映射为 branching candidates；
4. 尽可能复用 generic MILP features；
5. 替换 evaluator 为 UC SCIP evaluator；
6. 保持 LLM4Branch-style score_function search space；
7. 运行 SCIP default / pseudocost / most-fractional /
   LLM4Branch-style 四组 baseline；
8. 保存 program database；
9. 确认所有方法最终最优 objective 一致；
10. 暂不实现 structured branching。

完成后才能进入 Phase 1。
```

---

# 37. 最终论文实验逻辑

论文需要清楚分开两个创新来源。

## 37.1 Structured Search Space 是否有价值？

比较：

\[
\text{LLM4Branch-style + Base LLM}
\]

和：

\[
\text{Structured DSL + Base LLM}.
\]

如果后者提升，说明贡献来自：

> **UC structural branching design space。**

---

## 37.2 Solver-feedback post-training 是否有价值？

固定 structured DSL，比较：

\[
\text{Base}
<
\text{SFT}
<
\text{SFT+DPO}.
\]

重点不是只比较最终 best rule，还要比较：

- valid program rate；
- medium evaluator pass rate；
- top-decile fitness；
- best-of-N；
- reaching-target evaluations。

这样才能证明：

> 模型本身确实成为了更好的 algorithm designer。

---

# 38. 最终成功标准

项目成功必须同时满足：

### A. 不重复造轮子

通用 algorithm evolution infrastructure 基于成熟现有框架。

### B. Structured branching 有优化价值

\[
\text{Structured DSL}
>
\text{Variable-only baseline}
\]

至少在明确的 UC family / aggregate benchmark 上成立。

### C. Post-training 有价值

\[
\text{SFT+DPO designer}
>
\text{Base designer}
\]

在相同搜索预算下生成更高质量程序。

### D. 最终算法无需 LLM

\[
\boxed{
\text{Offline LLM discovery}
\rightarrow
\text{Frozen deterministic algorithm}
}
\]

### E. Test / OOD 泛化

最终规则在完全未参与：

- OpenEvolve search；
- BO；
- SFT；
- DPO；

的实例上仍具有收益。

---

# 39. 一句话项目定义

> **Reuse LLM4Branch/OpenEvolve as the algorithm-search infrastructure, extend the search space from variable scoring to UC-structured branching programs, post-train the open-source heuristic designer with solver-generated demonstrations and preferences, and finally deploy only the discovered deterministic branching rules.**

中文：

> **本项目复用 LLM4Branch/OpenEvolve 的自动算法搜索基础设施，将搜索空间从“变量评分”拓展到面向 UC 时空耦合结构的分支程序，并通过求解器生成的示范与偏好数据对开源大模型进行 SFT/DPO 后训练，最终仅部署自动发现的确定性分支规则。**
