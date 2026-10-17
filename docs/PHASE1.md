# Phase 1：最小 Structured Branching DSL

实现对应路线第 5、10 节。LLM 不在求解回调中运行；本阶段没有后训练，
没有重写 OpenEvolve，也没有进入 Phase 2 的性能实验或宣称通过 Gate 1。

## 对象与合法性

`src/ucbranch/structured.py` 提供路线约定的 frozen `BranchCandidate` 和
`BranchDecision`。决策只能引用当前候选池中的 kind/params，并给出有限 score。
候选包含 LP value、fractionality、size、depth，均来自当前节点。

| kind | 表达式 | 参数 |
|---|---|---|
| VAR | u[i,t] | unit, time |
| UNIT_ON_COUNT | sum(u[i,t]) | unit, start, end（两端包含） |
| START_COUNT | sum(v[i,t]) | unit, start, end（两端包含） |
| GROUP_ON_COUNT | sum(u[i,t] for i in group) | group, time |

默认时间窗口长度为 2、4，枚举每个合法起点。组为 FAST/SLOW、
BASELOAD/PEAKER、HIGH_START_COST/LOW_START_COST，分别按 ramp、cost、startup
排序分为两半，同值按 unit index 打破平局。组必须至少有两个成员。
这是可复现的初版划分而非物理类别标注；当前生成器 ramp 相同，FAST/SLOW
暂不能解释为真实速度差异。BLOCK_ON_COUNT 不在支持范围。

只有非整数且未局部固定的表达式进入候选池，整数判断使用 SCIP feasibility
tolerance。VAR 和 on count 的整数性显然；START_COUNT 使用模型中的连续 v，
但转移等式及 v/w 上界保证每个整数 commitment 解的 v 恰为启动事件。
因此 s <= floor(s*) 或 s >= ceil(s*) 覆盖全部整数可行解、两支互斥，
且都排除当前分数 LP 点。不能将这个推理套用到任意连续变量。

## SCIP 编译与回退

在求解前为每个 count 注册连续辅助变量 z = sum(...)，不新增整数变量。
回调使用原变量引用查询当前 LP，并取得 transformed alias；创建两个 child，
分别调用 chgVarUbNode / chgVarLbNode，实现子节点局部的计数不等式。
这不是给父节点添加割，也不会约束兄弟节点。局部固定的对象不参与选择。

当前 PySCIPOpt 4.4 无公开的线性表达式独立 constraint factory；多重聚合后的
alias 又不支持 node bound 操作。因此此兼容编译器关闭 presolve rounds/restarts
及 aggregation，完整设置写入结果。辅助变量本身也改变 LP 表示。
Phase 0 default 仅作最优值 reference，不能据此比较 nodes/time 并宣称收益。
Phase 2 必须增加相同扩展模型和参数的 variable-only 对照，并评估支持原生
局部表达式约束的编译后端，才能做公平性能实验。

默认规则按 fractionality 稳定选取；验收规则分别优先选择指定 kind，仅用于
确保每类编译路径实际执行。默认最大深度 8，验收为 2。超过深度、空池、
未知对象、NaN/Inf 分数和 policy 异常均返回 DIDNOTRUN，交由 SCIP 后续默认
branch rule 处理。不会把异常转成成功分支；SCIP 编译错误直接令求解失败。
策略输入深拷贝以保护编译元数据，但 Python policy 并非安全沙箱。

## 验收与复现

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .conda/llm4branch/bin/python -m pytest -q
.conda/llm4branch/bin/python scripts/phase1.py
```

`outputs/phase1/evidence.json` 保存实例、窗口、深度、源码 hash、solver 参数、
每个分支的表达式参数及 floor/ceil、fallback 计数和完整调度。
测试要求四类对象都实际创建 child，最终证明 optimal，并与原 UC 最优值一致；
另有整数调度穷举的析取覆盖检查、非法策略及深度回退测试。
这些是 Phase 1 正确性验收，不是 30–50 实例的 Phase 2 收益实验。

实测 Phase 1 的 9 项测试通过（174.75 秒），Phase 0 的 4 项回归测试通过
（10.98 秒）。两份锁定上游源码校验保持 clean，未修改第三方求解或搜索框架。
独立验收脚本在 seed 0、12 台机组、24 时段上对每类对象实际执行 7 次分支，
四次均达到 optimal，目标值均为 239463.06，与原模型一致。
