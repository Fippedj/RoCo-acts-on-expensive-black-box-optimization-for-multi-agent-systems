# ADR-0003：Stage 3 四角色协作状态机

- 状态：Accepted for Stage 3
- 日期：2026-09-19
- 上游：ADR-0001、ADR-0002、`docs/paper_spec/algorithm.md`、`docs/gap_registry.md` G-001–G-004/G-020–G-022
- 范围：单代 RoCo 协作、失败降级与运行 trace；不包含跨代记忆

## 背景

Stage 2 把 `collaboration_rounds` 当作配置兼容字段，只执行确定性的
E1/E2/M1/M2 路径。Stage 3 需要把论文中的四角色协作接入同一候选验证、
评估、预算和 Top-N 基线，同时保留原有 Stage 2 smoke 的调用数与选择行为。

论文明确了 Explorer、Exploiter、Critic、Integrator 的职责与默认三轮协作，
但没有给出可直接执行的消息 schema、全部失败语义或 trace 格式。附录 Critic
措辞还有 better/worse 歧义。因此本 ADR 区分论文约束与为离线、确定性实现所作
的工程决定。

## 决策

### 1. 四角色使用独立、版本化的契约

四个角色可以共享同一个 provider，但请求必须携带角色、动作、代数、轮次、
温度、输入候选与当前轮反馈，并使用各自的 prompt 契约：

| 角色 | 输入重点 | 合法输出 | 默认温度 |
|---|---|---|---:|
| Explorer | 当前探索分支、已验证分数、Critic 反馈 | 一个强调结构新颖性的 `description` + `code` 候选 | 1.3 |
| Exploiter | 当前利用分支、已验证分数、Critic 反馈 | 一个保守精炼的 `description` + `code` 候选 | 0.8 |
| Critic | 待比较候选及其真实评估结果 | 非空结构化反馈；不得输出候选或虚构分数 | 1.0 |
| Integrator | 两路最终有效候选、分数和最新反馈 | 一个融合后的 `description` + `code` 候选 | 1.0 |

所有候选代码仍必须定义 `heuristic(distance_matrix) -> tour`。角色生成不能绕过
Stage 2 的 AST/签名检查、spawn 子进程、单候选 timeout 或预算账本。Critic 的
可执行契约以 evaluator 的优化方向和数值为准，并作为修订版 prompt 明确版本化；
不采用附录中可能反转 better/worse 的模糊措辞。

Stage 3 的 TSP 路径只支持最小化；配置和 `RoCoCollaborator` 必须拒绝最大化，避免
在 prompt/Mock Critic 明确使用“越小越好”时暴露一个语义不一致的伪通用接口。
最大化任务进入实现前需要版本化 objective 契约和对应测试。

论文默认 `T=3`。smoke 可以显式使用更小的 `T>=1` 以降低确定性测试成本；
实际角色温度和轮数必须保存在配置快照或 manifest 中。

### 2. Stage 2 与 Stage 3 使用清晰的配置分派

配置字段 `evolution.mode` 显式分派 `eoh` 与 `roco`；为兼容已有配置，字段缺省时
按 `eoh` 处理。旧 `configs/smoke/tsp_mock.yaml` 继续走纯 EoH Stage 2 路径。在该路径中，
`collaboration_rounds` 仍只做合法性/兼容性校验，候选序列、调用数和 Top-N 行为
不得因 Stage 3 而改变。

独立的 `configs/smoke/tsp_roco_mock.yaml` 选择 RoCo 路径，并使用同一个离线
`MockLLMProvider` 的角色感知接口。不得在 smoke 分派中回退到真实 API，也不得
读取网络或密钥。相同配置和 seed 必须重放相同的角色请求顺序、候选内容、稳定
候选 ID、评估分数和非时间预算计数。

### 3. 单代状态机

每一代只采样一对已评估精英作为本次 Stage 3 协作基座。单代按以下顺序执行：

1. 对种群确定性排名并以 seed 驱动的精英偏置规则采样候选对。
2. Critic 对候选对作初始比较，给两路后续生成提供反馈。该步骤是 round `0`，
   不计入 `T`。V1 的结构化响应只有一个反馈字符串，作为两路初始反馈共同使用；
   轮内 Critic 则对 Explorer/Exploiter 两路分别调用。
3. 对 `t=1..T`，Explorer 与 Exploiter 各生成一个候选；候选分别通过统一验证与
   evaluator；Critic 分别比较各分支的前一有效版本与本轮结果并提供反馈。两路
   proposal 的 prompt 输入在该轮开始时固定，调用顺序不得造成隐式信息泄露。
4. `T` 轮结束后，Integrator 融合两路最后可用的候选、真实分数与反馈；融合结果
   仍是一个必须验证和评估的新候选。Integrator 不算额外协作轮。
5. 有效、已评估的 EoH 候选、协作候选和原种群进入同一个确定性 Top-N。LLM 的
   自评或 Critic 文本不能代替目标函数分数。

初始 Critic、每轮反馈和最终 Integrator 是代内短期状态。它们随本代 trace 保存，
下一代不得把其作为检索记忆自动注入 prompt。

正常、无失败时，每代 RoCo 分支发起 `1 + 4T + 1 = 4T+2` 次角色调用：一次初始
Critic，每轮两个 proposal 与两个分支 Critic，以及一次最终 Integrator；生成并最多
评估 `2T+1` 个候选。`T=3` 时对应 14 次调用和 7 个候选。EoH 调用、初始化和失败
调用仍按原账本规则另计，不能把该推演当作 400-call 论文预算的隐式配置。

### 4. 失败与预算耗尽时 fail closed

每次角色调用、解析、验证和评估都是显式事件。预期失败被转换为结构化状态，
而不是使整次 run 崩溃：

- 角色响应缺字段或类型错误：记录 `invalid_output`；不臆测自由文本内容。
- Explorer/Exploiter 候选未通过验证、超时或评估失败：记录失败，不进入 Top-N；
  分支继续保留最近一个有效、已评估的候选作为安全基座。
- Critic 失败：记录失败并以无新增反馈的保守输入继续；不得伪造比较结论。
- Integrator 失败：不产生融合候选；其他有效候选仍可正常进入 Top-N。
- 任一硬预算阻止新动作：记录 `budget_exhausted`，停止发起后续消费动作，使用已经
  完成的有效候选收尾。预算未允许的角色调用或评估不得先执行后补账。

未知的编程错误仍应在测试中暴露；上述降级只覆盖 provider/角色输出、候选验证与
评估、以及预算等运行时边界。

### 5. 每代写入可序列化 collaboration trace

Stage 3 trace 的 schema 版本为 `roco-collaboration-trace-v1`。每代 trace 至少包含：

```text
schema_version
scope
generation
elite_pair[] (完整、可序列化的 Candidate 快照)
elite_pair_ranks[]
sampling_power
sampling_seed, sampling_weights[]
rounds_requested, rounds_completed
stopped_on_budget
events[] (按实际状态机顺序):
  event_id, action, role, round, target_branch
  temperature, prompt_version
  input_candidates[], input_feedback[]
  output_candidate | output_feedback
  evaluation | null
  budget_before, budget_after, budget_delta
  status
  error_type, error_message
selected_candidate_ids[]
```

`scope` 固定为 `generation-local`，`elite_pair_ranks` 使用排序后从零开始的下标。
采样 seed、实际排名权重和结果都随 trace 保存。
`action` 区分初始 Critic、轮内 proposal/compare 与最终 integrate；`round=0` 只用于
初始 Critic，精炼轮使用 `1..T`，Integrator 记录在终止位置 `T` 但不增加完成轮数。
候选对象通过稳定 ID 引用，候选快照同时保留完整字段，便于脱离内存种群检查一次
角色调用。
`budget_before`/`budget_after` 是单调账本快照，必须能解释失败调用是否已计费。
`status` 至少能区分成功、角色输出无效、候选无效、预算耗尽和 provider 失败；
错误只保存可序列化的 `error_type` 与 `error_message`，不保存异常对象。

trace 是运行审计日志，不是可供后续代检索的知识库。墙钟与 runtime 字段可以因
机器调度而变化；Mock 可重放保证针对角色顺序、候选、分数和离散预算计数，而不
要求时间测量逐字节一致。

## 与论文的对应及工程简化

本状态机对应论文的“精英对 → 初始 Critic → `T` 轮 Explorer/Exploiter 精炼与
Critic 反馈 → Integrator → 与 EoH 统一 Top-N”骨架，并采用论文登记的角色温度和
`T=3` 默认值。

Stage 3 的确定性 Mock、结构化消息、一次一对精英、串行调度、稳定 ID、失败降级、
初始反馈共用一个字符串和 trace schema 是工程决定，不是论文披露值。当前状态机
只在 `T` 轮之后调用一次 Integrator；论文资料中可能暗示轮内 Integrator 的表述保留
为歧义，若未来复核后改变必须新版本化并同步预算公式。Mock 证明的是控制流与预算
可审计，不构成论文性能复现。Stage 3 也不承诺真实 LLM 在相同 seed 下逐字节重放。

## Stage 4 边界

Stage 3 明确不实现：

- LTReflect 或角色长期摘要；
- 跨代事件存储、检索、截断或记忆恢复；
- memory-guided mutation；
- 向量库、相似度召回或任何其他长期记忆后端。

ADR-0001 中有关 JSONL 长期记忆和每个精英三角色记忆变异的决定继续延期到
Stage 4。Stage 3 的 collaboration trace 即使落在 JSON/JSONL 运行日志中，也不能
被解释成已经实现上述机制。

## 后果

正面结果是 `collaboration_rounds` 在独立 RoCo 路径中具有可测试语义，四角色调用
和失败都可追溯，且所有可执行候选继续共享 Stage 2 安全/预算边界。代价是串行
`T` 轮显著增加 Mock 调用和评估数；失败时保留最后有效分支可能弱化协作质量；
单代 trace 不能提供长期学习。这些限制由后续阶段或新的 ADR 显式替代，不能静默
扩展为 Stage 4 功能。
