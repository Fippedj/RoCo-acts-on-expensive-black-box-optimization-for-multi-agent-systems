# RoCo 参数登记表

## 读取规则

- “明确披露”只表示当前精读材料可定位到论文陈述，不表示官方代码或完整实现已公开。
- `S009` 在 `paper.md` 中标为 p.5 与 p.12–13，但 `source_map.json` 只把该块挂到 p.5；涉及附录参数时保留这一证据粒度差异，待对原 PDF 复核。
- “第一版工程默认值”不是论文值时一律标记为工程决策；运行清单必须同时保存实际值。

| 参数名 | 论文给出的值 | 证据页码 / 块 ID | 是否明确披露 | 第一版工程默认值 | 说明 |
|---|---:|---|---|---:|---|
| `llm.model` | GPT-4o-mini | p.5、p.12–13 / `S009` | 是 | `gpt-4o-mini`；本地/CI 由 Mock 替代 | 服务端模型快照未披露；V1 优先 Mock 不等于论文模型 |
| `evolution.population_size` (`N`) | 10 | p.5、p.12–13 / `S009`；Top-N 见 p.3 / `S005` | 是 | 10 | Top-N 的 tie-break 未披露 |
| `evolution.collaboration_rounds` (`T`) | 3 | p.5、p.12–13 / `S009`；流程见 p.10 / `S008` | 是 | 3 | 初始 Critic 和最终 Integrator 不计入 `T` |
| `evolution.elite_sampling_power` (`k`) | 3.0 | p.10–13 / `S008`、`S009`（精读汇总） | 是，但 source map 粒度不足 | 3.0 | 排名权重按 `1/(i+1)^k`；边界和相邻伙伴细节仍需原 PDF 逐式复核 |
| `llm.temperatures.explorer` | 1.3 | p.12–13 / `S009`（精读汇总） | 是，但未单列原文块 | 1.3 | 运行时必须记录 |
| `llm.temperatures.exploiter` | 0.8 | p.12–13 / `S009`（精读汇总） | 是，但未单列原文块 | 0.8 | 运行时必须记录 |
| `llm.temperatures.critic` | 约 1.0 | p.12–13 / `S009`（精读汇总） | 部分明确 | 1.0 | 精读材料称“其余约 1.0”；精确 API 参数待 PDF/作者代码复核 |
| `llm.temperatures.integrator` | 约 1.0 | p.12–13 / `S009`（精读汇总） | 部分明确 | 1.0 | 同上 |
| 每代 LLM API 预算 | 400 calls / generation | p.5 / `S009` | 是 | `max_llm_calls: null`，实验必须显式设硬上限 | 不能自动等同于评估次数；`null` 防止伪装成已解决口径 |
| 最大评估预算 | maximum 400 evaluations | Appendix D（`START_HERE.md` 与路线图的冲突记录；当前 source map 无独立块） | 有陈述但证据锚点不足 | `max_valid_evals: 400` | 与“每代 400 calls”可能是不同实验口径；必须分别记账并在 manifest 声明作用域 |
| `G`（总代数） | 未披露/无法由当前材料唯一确定 | p.10 / `S008` 仅描述代循环；`S011` 指出成本口径不完整 | 否 | 不写死；由显式预算终止 | smoke 配置中的 `G=2` 只能是工程测试值 |
| 精英对数量/每代协作次数 | 未披露到可执行粒度 | p.10 / `S008` | 否 | 待 Stage 2 配置化 | 直接影响调用数和候选数，不能从 400 反推 |
| 每个精英的记忆变异数 | 三种角色视角 | p.10 / `S008` | 角色数明确，精英集合大小不明确 | 每个精英 3 个（Explorer、Exploiter、Integrator） | ADR-0001 固化 V1 |
| `memory.recent_events` (`K`) | 未披露 | p.4 / `S007`；缺失性见 p.10–16 / `S011` | 否 | 5 | ADR-0001 工程决策 |
| `memory.backend` | 未披露 | p.10–16 / `S011` | 否 | JSONL | ADR-0001 工程决策 |
| 每角色输入/输出 token 上限 | 未披露 | p.10–16 / `S011` | 否 | 暂不在 paper preset 伪设数值；Stage 2 必须显式配置 | 路线图中的 6k/1.2k、4k/500、6k/250 是建议，不是论文值 |
| 无效代码修复重试 | 未披露 | p.10–16 / `S011` | 否 | 最多 2 次（待后续 ADR/配置） | 每次修复仍计 LLM call；本阶段不实现 |
| `run.seed` | 未披露 | p.10–16 / `S011` | 否 | 2025 | 纯工程默认值；必须记录所有随机源 |
| 普通训练超时 | 当前精读材料未给出可独立核验值 | `S009` 涵盖 p.12–13 实验设置，但无逐项原文；`S011` | 否/证据不足 | 60 s | 现有配置值仅作工程占位，需在 Stage 2 evaluator 协议前复核 PDF |
| CVRP 训练超时 | 当前精读材料未给出可独立核验值 | 同上 | 否/证据不足 | 120 s | 现有配置值仅作工程占位，不能称论文默认值 |
| TSP 规模 | TSP-50、TSP-100、TSP-200 出现在结果表/GLS 比较 | p.6–7 / `T001`–`T004` | 是（规模），否（完整 instances） | 三个规模均由版本化 deterministic generator 提供 | 坐标分布、种子、test count 与 corpus checksum 未由当前材料确认；见 G-034 |
| TSP 训练实例数 | 举例为 5 个 TSP instances | p.5、p.12–13 / `S009` | 是（训练数陈述），否（具体实例） | P6 default 每 split/size 1，仅为快速 dry-run | 工程 inventory 不得替代论文训练集或暗示相同数据分布 |
| P6 dry-run seeds / split count | 未披露到可执行粒度 | `S011`；G-018/G-034 | 否 | `[101, 202, 303]`，每规模 train/test 各 1 | 固定三 seed 是接口验收条件，不是论文的独立运行设定 |
| P6 all-method hard ceilings | 未披露统一可执行规则 | G-012/G-021 | 否 | 24 calls、120000 Mock tokens、24 candidates、24 valid evals、1 USD、120 s | ADR-0006 工程公平定义为同上限，实际消耗另报；不是论文预算 |
| white/black visibility prompt | 两种 setting 存在，但完整 prompt 未可执行披露 | p.1–2 / `S003`；`S011` | 部分明确 | `roco-prompt-visibility-v1` metadata-only Mock condition | 不是昂贵 oracle；真实 prompt 内容/效果仍为 G-035 |
| EoH E1/E2/M1/M2 每算子候选数 | 未披露到当前 source blocks | p.3 / `S005` | 否 | 待 Stage 2 配置化 | 必须纳入 candidate/call 数量推演 |
| Top-N tie-break | 未披露 | p.3 / `S005` | 否 | 稳定排序 + 明示的候选 ID tie-break（待实现 ADR） | 不得依赖并行完成顺序 |

## P7a 跨 COP 参数权威定义

本节是 P7a 及未来 P7b 的跨 COP 参数**唯一权威定义**；
`multicop_experiment_protocol.md` 定义这些字段如何进入 run record。它不改写 P6 的 TSP-only
config：P6 的 3 seeds 与 `24/120000/24/24/1 USD/120 s` 仍只适用于 ADR-0006 dry-run，不能
被读成下列真实/多 COP 实验的默认值或论文参数。

| 参数名 | 论文给出的值 | P7a 预注册定义 | 适用与证据边界 |
|---|---|---|---|
| `experiment.benchmark_id` / `benchmark_version` | 非 TSP COP 未由本地材料确认 | 不可变问题标识和 evaluator-compatible version；每个 run 必填 | 候选 COP 在 E0–E2 只能登记，不能标为 supported；见 G-037/G-039 |
| `dataset.source_id` / `release` / `license_id` | 未披露到可执行粒度 | 获授权来源、release/version 和许可证标识均必填 | 无三者不得下载、适配或运行；见 G-037 |
| `dataset.inventory_checksum` / `instance_checksum` | 非 TSP 未披露 | canonical inventory 和每个 instance 的 SHA-256；两者均必填 | checksum mismatch fail closed；见 G-038 |
| `dataset.split_policy_version` / `split` | 论文 split 细节不足 | 明示 train/validation/test 规则，semantic/geometry-equivalent instance 不得跨 split | 方法选择只可用 train/validation；test 在设计冻结后使用；见 G-034/G-038 |
| `experiment.seed_set` / `derived_run_seed` | 未披露 | 运行前固定 root seed set；按 benchmark/version/instance checksum/split/condition/method 派生 | 同一比较 cell 的方法必须匹配 seeds；P6 `[101,202,303]` 仍是 P6-only；见 G-018/G-036/G-040 |
| `budget.profile_id` / `budget.hard_limits` | G-012 仍冲突 | 同时声明 calls、input/output tokens、generated candidates、valid evaluations、cost、wall time 六维 hard ceilings 和作用域 | 同 cell 所有方法使用相同 profile；实际消耗另报，P6 profile 不外推；见 G-012/G-021/G-040 |
| `prompt_visibility.contract_version` / `condition` / `allowed_fields_hash` | 两个 setting 存在，完整 prompt 未披露 | visibility 是版本化信息集；记录 condition、允许字段 hash、prompt version/hash 与禁止字段 | 不是昂贵 oracle；比较单元不得混用 condition；见 G-035/G-040 |
| `provider.name` / `network_state` / `model` / `adapter_contract` | 仅部分模型名披露 | 记录 provider、network、model snapshot、adapter、tokenizer counter、pricing、temperature/concurrency 版本 | Mock 可重放非时间状态；真实 provider 另需授权，不能伪称确定性；见 G-009/G-030–G-033/G-040 |
| `evaluation.objective_direction` / `evaluator_contract` / `timeout_scope` / `metric_name` / `reference_version` | 非 TSP COP 未披露 | 在 run 前冻结 minimize/maximize、constraints、feasibility、timeout scope、primary metric 和可选 reference | 不同 evaluator/reference 的 raw score/gap 不可直接比较；见 G-016/G-039 |
| `mkp.dataset.protocol_version` / `split_policy_version` | FSU 数据不是论文实验 corpus | `mkp-fsu-protocol-v1` / `mkp-fsu-protocol-only-v1`；P01–P06 全部为 `protocol-only`，无 train/validation/test | 仅供 E3 integration；不得训练、调参、统计或称正式 benchmark；见 G-038 |
| `mkp.evaluation.score` / `normalized_score` | 未披露 | 来源 maximize `raw_profit`；系统唯一选择分数为 minimize `-raw_profit`；审计归一化为 `score/max(1,sum(max(0,profit)))` | normalized 值不参与 Top-N，不是 reference gap；optional reference 不进入 prompt/打分；见 G-039 |
| `mkp.experiment.root_seed` / seed derivation | 未披露 | E3 Mock root seed `707`；按 protocol version/instance checksum/split/full_instance/method 派生 run seed，再派生 provider/collaboration seed | 单 seed 只验证接口/重放，不满足 G-041 统计重复数 |
| `mkp.budget.profile_id` / hard limits | 未披露 | `mkp-fsu-mock-engineering-v1`：20 calls、50000 combined Mock tokens、16 candidates、16 valid evals、USD 0.25、60 s | 对 P01–P06 的 EoH/RoCo 相同；不是 P6 profile、论文预算或 E4 默认；见 G-040 |
| `mkp.prompt_visibility` / provider | 未披露 | 唯一 `full_instance`：capacity/weight/profit/目标/约束/签名；排除 optional reference/optimum；Mock `network=unused` | 不做 white/black 对比，不是昂贵 oracle；真实 provider 另行授权；见 G-040 |
| `statistics.planned_repetitions` / `seed_set_id` | 未披露 | 每个可比较 cell 最低 10 个匹配独立 seeds；完整 seed set 运行前固定 | 少于 10（包括 P6 3-seed Mock）只能作描述性接口审计；见 G-041 |
| `statistics.bootstrap` | 未披露 | 10,000 次 paired bootstrap、95% percentile interval，只用于同 cell 匹配完成 pairs | 不是 p-value；不使用显著性措辞，不跨 COP 聚合；见 G-041 |
| `statistics.failure_policy` | 未披露 | planned/completed/failed 全记录；失败不删除、不重抽 seed、不插补 score；completed-only 必须标条件性 | 失败率/原因与 objective 同报；见 G-041 |

## Stage 6 EBBO 设计参数

本节登记 ADR-0008 与 `ebbo_design.md` 的设计参数。它们不是 RoCo 论文披露值，也不表示运行时代码
已经实现。`unset` 表示必须在对应 P9 子任务开始前以 gap 关闭证据和版本化配置决定，调用方不得自行
选择一个库默认值。

| 参数名 | Stage 6 冻结值/候选 | 当前状态 | 适用与证据边界 |
|---|---|---|---|
| `ebbo.problem.objective_direction` | `minimize`，单一 primary objective | 设计冻结 | maximize/多目标需新 contract；约束统一为 `g_i(x) <= 0` |
| `ebbo.oracle.request_schema` / `result_schema` | `ebbo-oracle-request-v1` / `ebbo-oracle-result-v1` | 概念契约冻结；未实现 | 真实 endpoint、credential、网络和付费 oracle 不在 schema 或当前授权中 |
| `ebbo.observation.schema` / `status_contract` | `ebbo-observation-v1` / ADR-0008 状态转换 | 概念契约冻结；未实现 | 失败 Observation 不含惩罚 objective；late result 不覆盖终态 |
| `ebbo.budget.ledger_schema` | `ebbo-ledger-v1`；oracle calls、成功/失败 evaluations、candidate proposals、LLM calls/tokens、source+unit cost、wall-clock 分账 | 概念契约冻结；未实现 | 不修改现有 `BudgetLedger`；代码边界/迁移见 G-042 |
| `ebbo.budget.acceptance_rule` | oracle 接受的每个 attempt 永久计 `oracle_calls` 与可确认实际成本 | 设计冻结 | timeout、失败、接受后取消和实际重复接受均不退款 |
| `ebbo.run.root_seed` / `seed_derivation_version` | `unset` / `unset` | P9a 前决定 | Mock oracle、surrogate、pool、acquisition、角色、scheduler 必须用分离 label；见 G-042 |
| `ebbo.oracle.mock_contract` | deterministic、`noise.kind=none`、`max_concurrency=1` | P9a 范围冻结；函数/benchmark 未选择 | 只证明控制流、审计和 replay，不是昂贵真实实验；见 G-045/G-046 |
| `ebbo.surrogate.family` / `fit_contract` | `unset` | 开放 | 不假定 GP、神经 surrogate 或第三方 BO 库；见 G-043 |
| `ebbo.acquisition.id` | EI、UCB、Thompson sampling 是未来候选 | 开放 | P9a 必须预选一种作为单 agent baseline；多种 acquisition 分别成实验 cell；见 G-044 |
| `ebbo.candidate_pool.size` / `optimizer` / `tie_break` | `unset` | 开放 | pool 必须有限、版本化、可审计；角色不得选择池外候选；见 G-044 |
| `ebbo.noise.model` / `replication_policy` | P9a Mock 为 none/默认不 replicate；真实设置 `unset` | 部分冻结 | 噪声聚合、重复评估和 latent/observed regret 见 G-046 |
| `ebbo.constraints.contract` / `failure_model` | optional `g_i(x) <= 0`；具体约束和模型 `unset` | 开放 | 失败不得变成惩罚 objective；约束 BO/失败建模见 G-047 |
| `ebbo.cost.model` / `cost_aware_acquisition` | unit-aware；具体模型 `unset` | 开放 | 不同单位/币种禁止隐式相加；预计与实际成本并存；见 G-049 |
| `ebbo.scheduler.max_concurrency` | P9a/P9b 为 `1`；P9c `unset` | 串行范围冻结，异步开放 | reservation/pending/取消/recovery/late result 见 G-048 |
| `ebbo.roles` | global explorer、local exploiter、model critic、resource integrator | 设计冻结；P9b 未实现 | Integrator 只引用有限 pool entry，scheduler 唯一 dispatch；见 G-051 |
| `ebbo.evaluation.primary_metric` | simple regret（仅有可靠 reference 时） | 原则冻结，reference 未定 | cumulative regret、cost-to-target、failure/time 指标需预注册；见 G-050 |
| `ebbo.statistics.seed_set` / `repetitions` / `target` | `unset` | P10 前决定 | 没有 E4 工件不得作性能、显著性、泛化或优越性结论；见 G-050 |

## 400 calls 与 400 evaluations 的处理

两句话不能互相替代：一次调用可能不产生候选、产生无效代码或产生一个待评估候选；一次候选评估也可能因修复、缓存、重复或超时而与调用数不一一对应。第一版因此分别记录 `llm_calls`、`tokens`、`generated_candidates`、`valid_evals`、`cost`、`wall_time`，每个实验显式指定至少一个硬停止预算。复现实验报告必须同时展示各账本值，不能把“达到 400 calls”写成“达到 400 evaluations”。

## 训练超时处理

`configs/paper_defaults.yaml` 现有的 60/120 秒值继续保留，以免无证据改变行为，但注释应明确它们是待核验的工程占位值。Stage 2 在实现 evaluator 前需要回看原 PDF 的 Appendix D/实验设置，确定超时作用于单实例、单候选、单求解器运行还是整批训练；在此之前不得用 `paper_*` 命名或报告成作者原设定。
