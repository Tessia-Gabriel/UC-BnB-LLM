# Phase 2：人工 Structured Branching 可行性实验

本阶段不调用 LLM、不调参、不执行 SFT/DPO。目标是检验 DSL 的实际收益，
不是仅验证最优值。Phase 1 的兼容编译器保留原样，新增独立实验适配器。

## 固定协议

- 30 个开发实例：10/20/50 台机组 × 5 场景 × seeds 100/101；8 时段。
- 场景：normal、tight_ramp、high_startup、peak、combined。
  紧爬坡为 8+(i mod 3)，普通为 20+(i mod 3)；高启动成本为原值三倍；
  peak 将时段 4 需求设为总容量的 82%。不是标准数据集或 Test/OOD。
- 每次 SCIP 限时 3 秒、单线程、固定 solver seed；各实例轮换方法执行顺序。
  这是短预算可行性 pilot，不是充分预算或统计显著性的最终性能实验。
- 连续计数辅助变量、窗口 2/4、关闭预处理的配置在六个 matched 方法间一致。
  另保留未经扩展的 native_default，以量化编译器整体代价。
- 三条规则固定阈值 fractionality >= 0.25、只在深度 <= 2 使用结构分支：
  start 优先 START_COUNT；temporal 优先 UNIT_ON_COUNT；hybrid 依次尝试
  START_COUNT、UNIT_ON_COUNT、GROUP_ON_COUNT。其余情况回退 pseudocost。
- controls：native_default、matched_default、pseudocost、llm4branch。
  后两者直接使用锁定 Ecole 的 observation；LLM4Branch-style 直接加载
  Phase 0 的固定评分源码、特征 9/43、参数 0.5/0.5 和原版 normalize。
  它不是新的 LLM 搜索结果，也不是所有可能 variable-only 规则的上界。

`src/ucbranch/phase2.py` 将 Ecole observation 接到同一 PySCIPOpt solver，
没有 environment reset/copy，因此全部方法能使用同一个事件监测器。
native_default 和 matched_default 不注册自定义变量或结构分支策略。

## 指标与正确性

保存 solver_time、包含建模/特征初始化的 wall_time、nodes、首次 incumbent
时间、final_gap、primal/dual、完整调度、结构分支和变量分支次数。
每个可行调度独立检查约束和成本；同一实例的 optimal 目标必须一致，
超时 incumbent 不得低于已证最优值，dual 不得超过已证最优值。
超时不算 solved，未找到 incumbent 的首次解时间保持 null。

此锁定 PySCIPOpt 无原生 primal-dual-integral getter。指标明确命名为
`primal_dual_integral_sampled`：在 LP/node/incumbent 事件采样，积分
min(1, |primal-dual|/max(|primal|,|dual|))，缺失界或异号记 1，采用左端保持，
将终点 gap 延伸到共同时间预算。保留完整采样轨迹；它是事件采样近似值，
不是声称精确复现 SCIP 原生积分。最佳解事件记录首次 incumbent 时间。

## Gate 1 判定

为避免单 seed 偶然赢家，按预先定义的每个 scenario 的 6 个实例判定。
一条结构规则必须实际分支，在该组全部求解为 optimal，并相对四个 controls
都至少降低 10% 的总 nodes 和 wall_time，采样积分不恶化超过 5%，才作为
候选收益证据。单次短预算 pilot 即使满足条件也需要重复确认，不是最终部署证据。
失败只表示此次协议未证实收益，不能推断所有 structured branching 无效。

## 复现

```bash
.conda/llm4branch/bin/python scripts/phase2.py --output outputs/phase2-run-v2
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .conda/llm4branch/bin/python -m pytest -q
```

脚本逐次原子保存结果，支持同目录恢复，但拒绝源码/协议变动后的混合恢复。
协议先于求解写入，包含全部实例、源码 hash、阈值、预算和方法。
可用 `--limit` 指定后续更大预算，但必须使用新的输出目录。
不要并发运行计时实验。最终结果见该目录的 `summary.json` 和逐次 JSON。

## 后端评估

当前绑定缺少独立线性约束 factory，多重聚合 alias 无法直接设置子节点界。
为避免未验证的 C 指针操作或修改锁定上游，本阶段使用同扩展模型对照来
隔离策略收益，并同时测原生模型。未实现原生局部表达式约束后端。
若 Gate 1 未通过，应优先研究该后端及更少的窗口/候选，在相同设置下重跑；
不得进入后训练，也不能把同扩展模型上的局部优势当成端到端收益。

## 验证记录

全量回归为 17 passed（184.82 秒），资源释放修订后的 Phase 2 专项复测
为 4 passed（3.09 秒）。锁定 LLM4Branch/Ecole 源码保持 clean。
`outputs/phase2-final` 是发现 pseudo-solution 回调缺失时的中断试跑，
不参与正式汇总；正式目录为 `outputs/phase2-run-v2`。
对超时实例，较低 nodes 不代表更快，可能只是在 root LP 花费了更多时间；
因此不能脱离 solved rate、gap 和共同预算解读平均节点数。

## 正式结果与结论

`outputs/phase2-run-v2/summary.json`：210/210 次评估完成，全部得到通过
独立校验的可行调度，共执行 585 次结构分支；这不等于 210 次均证明 optimal。
同实例已证最优值一致，超时 incumbent/dual 与已知最优值未出现矛盾。
协议中全部源码 hash 已核对一致。

| 方法 | optimal / 30 | timeout | 平均 wall 秒 | 平均采样 PDI | 平均 final gap |
|---|---:|---:|---:|---:|---:|
| native_default | 21 | 9 | 1.725 | 0.3370 | 0.1443% |
| matched_default | 14 | 16 | 2.335 | 0.2501 | 0.3061% |
| pseudocost | 13 | 17 | 2.226 | 0.2474 | 0.4069% |
| llm4branch | 11 | 19 | 2.247 | 0.2471 | 0.3621% |
| start | 13 | 17 | 2.253 | 0.2458 | 0.2436% |
| temporal | 13 | 17 | 2.253 | 0.2467 | 0.3290% |
| hybrid | 12 | 18 | 2.256 | 0.2457 | 0.2541% |

**本轮 Gate 1 未通过，不进入 SFT/DPO。** 没有任何预定义场景组满足收益门槛。
不同指标存在取舍：扩展模型更早产生 incumbent，采样 PDI 较低；原生 SCIP
的 solved rate 和总运行时间更好，不能用单个积分指标宣称整体超越。
局部例子是 n10/high_startup/100 的 start 使用 13 nodes，matched_default
为 27，但 native_default 只需 1；这只是局部信号，不是端到端优势。

下一轮优先顺序：验证保留正常预处理的原生局部约束编译后端；减少冗余窗口
和组候选；对 root-only/更严格触发的 hybrid 做预注册对照；再扩大时限并做
重复评估。此次结果不能区分辅助变量和关闭预处理各自的贡献，需单独消融。
3 秒、8 时段、每例单次、共享硬件的限制必须随结果保留，不作 Test/OOD 泛化结论。
