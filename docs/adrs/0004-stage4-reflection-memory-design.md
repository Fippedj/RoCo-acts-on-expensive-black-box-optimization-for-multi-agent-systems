# ADR-0004：Stage 4 反思记忆与记忆引导变异设计

- 状态：Accepted for Stage 4 implementation
- 日期：2026-09-19
- 上游：ADR-0001、ADR-0003、`docs/paper_spec/memory.md`、`docs/gap_registry.md`
- 范围：LTReflect、跨代角色记忆、记忆引导变异和代级恢复；本 ADR 本身不实现运行时代码

## 背景

Stage 3 已实现四角色的代内协作和 `roco-collaboration-trace-v1`。该 trace 是完整的
运行审计记录，但其事件粒度、失败信息和当前轮反馈不等同于可检索的长期记忆。
Stage 4 需要把论文中的长期反思和 memory-guided mutation 变成可测试协议，同时
保持离线、确定性、预算可审计和失败不致使整次运行崩溃。

论文明确长期反思应保留修改前后的目标值及变化，并以 Explorer、Exploiter、
Integrator 三个视角产生记忆引导变异。论文没有完整披露事件 schema、检索配额、
摘要格式、原子提交、崩溃恢复、上下文截断和重复候选策略。以下内容因此分别标注
为“论文约束”“合理推断”或“工程决定”，不得作为作者原始实现宣称。

## 决策

### 1. 审计 trace 与长期记忆是两个版本化边界

`roco-collaboration-trace-v1` 保持不变，并继续作为一次 run 的事实来源。Stage 4
只从一代已经完成的 trace、候选评估和最终 Top-N 结果派生长期事件，不直接把 trace
文件当作检索库。长期事件使用独立 schema `roco-memory-event-v1`。

这是工程决定。转换器必须是纯函数：相同 trace、候选集合、选择结果和配置产生
相同的规范化事件及 `event_id`。墙钟时间不参与 ID、排序或哈希。

### 2. `MemoryEvent` 的最小可执行 schema

每条事件至少包含：

```text
schema_version = "roco-memory-event-v1"
event_id                       # 规范 JSON 的稳定摘要
run_id, benchmark, objective
generation, round, sequence
role                           # explorer | exploiter | integrator
event_kind                     # mutation | invalid_output | invalid_candidate |
                               # evaluation_failure | budget_exhausted
source_trace_event_ids[]
parent_candidate_ids[]
output_candidate_id | null
before_score | null
after_score | null
delta_g | null
improved                       # true only when comparable and delta_g > 0
success                        # valid, evaluated, finite output candidate
selected_in_population
feedback | null
failure_type | null
failure_message | null
budget_before, budget_after, budget_delta
prompt_version, provider_name, model_name
```

候选代码不复制进长期事件；事件只存稳定候选 ID，并由同一 run 的候选/trace 工件
解析。反馈和错误文本必须有确定性长度上限并经过控制字符清理；不得保存 API 密钥、
环境变量、异常对象或完整原始对话。

`delta_g` 统一表示“越大越好”的改善量。当前只支持最小化：

```text
delta_g = before_score - after_score
```

只有两个分数均为有限数值时才计算。无效输出、timeout、预算耗尽或缺少结果时
`after_score`/`delta_g` 为 `null`，`success=false`，不能伪造惩罚分。未来支持最大化时
必须发布新 objective 契约；不能仅在实现里悄悄反转公式。

Explorer/Exploiter 事件以分支上一有效候选为 before、proposal 为 after；对应 Critic
反馈通过 source trace ID 绑定，但事件角色仍是被评价的生成角色。Integrator 以两个
输入父代中最优分数作为 before。初始 Critic 没有干预结果，不单独进入长期事件。
失败 proposal 仍形成负面事件，以便反思失败模式。

### 3. 摘要是可重建派生物，不是真实事实源

每代为 Explorer、Exploiter、Integrator 各生成一次长期摘要，schema 为
`roco-role-memory-summary-v1`。摘要至少包含角色、版本、截至代数、来源 event ID、
来源集合哈希、prompt/provider 版本、成功策略、失败模式、适用条件和应避免模式。

三次摘要调用是工程 multiplicity，不是论文披露值。Explorer/Exploiter 摘要供各自
mutation 使用；Integrator 摘要可读取两者的结构化摘要和 Integrator 历史，但不能
读取未提交的未来事件。Critic 反馈作为事件证据保存，Stage 4 V1 不创建单独 Critic
长期摘要，因为 Critic 不产生 memory-guided mutation。

摘要输出非法或调用受预算阻止时，保留上一个已提交摘要并记录失败。没有旧摘要时
使用空摘要；不得阻止 Top-N 或整次 run。摘要文件包含来源哈希，因此可从事件重建，
也能检测陈旧或损坏内容。

### 4. 检索默认 `K=5`，采用确定性 3/2 成败平衡

检索只读取上一代及更早的已提交事件，作用域必须匹配 benchmark、objective 和角色。
默认最多 `K=5`：优先取最近 3 条 `success && improved` 事件和最近 2 条其他事件。
若一类不足，用另一类按新到旧补满。最终注入顺序按 `(generation, round, sequence,
event_id)` 升序排列，保证重放稳定。

“其他事件”包括有效但未改善的候选以及结构化失败；因此失败经验不会被“有效事件”
措辞意外排除。当前代的新事件不参与本代检索，只通过当前 LTReflect 摘要进入 prompt，
避免未提交状态和失败恢复改变召回结果。

`K=5` 来自现有复现口径；3/2 配额、作用域和补位是工程决定，必须保存在配置快照。

### 5. 每个配置化精英产生三个记忆引导候选

在 Stage 3 的最终 Integrator 之后、统一 Top-N 之前，选取排名最前的 `elite_count`
个有效精英。默认 `elite_count=1`（工程值）。每个精英依次发起 Explorer、Exploiter、
Integrator 三次 mutation 调用；每次输入包含：

1. 任务与 objective 契约；
2. 当前精英候选和真实分数；
3. 对应角色的累计摘要；
4. 最多 K 条带数值证据的历史事件；
5. 严格的单候选 JSON 输出契约。

三个输出都经过既有 AST 检查、spawn evaluator、timeout 和预算账本，再与 EoH、
Stage 3 协作候选及原种群统一进入 Top-N。无效或受预算阻止的 mutation 记录失败后
安全跳过，不触发自动修复或重试。

Stage 4 每代相对 Stage 3 的理论上限为 `3` 次摘要 LLM 调用，加上
`3 * elite_count` 次 mutation LLM 调用、生成候选和有效评估。实际数可能因预算、
非法输出或评估失败更少。摘要调用消耗 LLM calls/tokens，但不增加 generated
candidates 或 valid evaluations。

### 6. 上下文组装与截断必须确定且可审计

上下文按以下优先级保留：任务/输出契约与 objective、当前精英及分数、近期事件的
数值字段与 ID、累计摘要、事件反馈文本。超过配置上限时，先截断最旧事件的自由文本，
再删除最旧完整事件，最后截断摘要自由文本；不得删除输出契约、objective、候选 ID、
分数或事件来源哈希。

Mock 路径使用确定性的字符/字段预算，不声称等价于真实 tokenizer。每次组装记录原始
大小、最终大小、删除的事件 ID/字段和截断原因。真实 provider 接入前必须增加模型
tokenizer 契约，而不是复用字符估算冒充 token 精确值。

### 7. 记忆采用代级不可变 segment 和 commit-last 协议

每个 run 使用独立目录：

```text
memory/
  events/generation-000001.jsonl
  summaries/generation-000001-{role}.json
  checkpoints/generation-000001.json
  commits/generation-000001.json
```

写入顺序为：在同目录创建临时文件，写事件 segment、摘要和 checkpoint，刷新文件，
原子 rename 到最终名；最后原子写入 commit marker。commit marker 保存所有工件的
相对路径、字节长度、SHA-256、事件数、预算快照和配置哈希。读者只接受存在有效
commit marker 且所有哈希匹配的一代。临时文件、缺 commit 或哈希不匹配的工件忽略
并报告，不自动删除。

这是一种逻辑 append-only JSONL：已提交 generation segment 永不改写；全局事件流
按代号连接。它比向单一 JSONL 尾部直接追加更容易做到崩溃检测和幂等恢复。

checkpoint 至少保存下一代所需的完整 population、预算账本、代号、稳定随机流游标、
Mock provider 重放游标以及相关工件哈希。恢复从最后一个连续、哈希有效的 commit
开始；若下一代存在半写工件则忽略并以相同游标重算。实现必须用显式、JSON 安全的
随机/Provider snapshot 接口，不能依赖 pickle 或平台私有对象。

### 8. V1 不做内容去重或 evaluation cache

Stage 4 保持 Stage 2/3 预算语义：内容相同但 ID/谱系不同的候选仍作为新生成候选并
重新评估。系统可以记录规范代码哈希用于审计，但不得静默复用分数或节省 evaluation。
引入去重/cache 会改变预算、选择和记忆事件语义，必须另写 ADR 并增加 cache-hit 账本。

### 9. 失败隔离和提交边界

单个事件转换、摘要、检索、mutation 或评估失败只能丢弃对应派生结果。若代级记忆
提交失败，该代不得留下看似完整的 commit；运行可保留已选 population 并以明确
`memory_commit_failed` 状态停止或由最后提交点恢复。未知程序错误不能伪装为成功。

只有 Top-N 已完成且 `selected_in_population` 已回填后才能提交本代记忆。本代事件不
反向影响本代的历史检索，但其摘要可用于本代 mutation；恢复时摘要和 mutation 的
输入均由同一 checkpoint/来源哈希重建。

## 与论文的对应和简化

论文约束包括：长期反思保留修改前后目标值和变化；跨代经验用于下一步；Explorer、
Exploiter、Integrator 三种视角分别生成 memory-guided mutation。V1 的 JSONL segment、
稳定哈希、3/2 检索配额、每代三次摘要、`elite_count=1`、确定性截断、无 cache 和
commit-last 恢复协议均为工程决定。

离线 Mock 只能验证控制流、重放、预算和恢复，不能验证反思质量或论文性能。真实 API、
向量检索、语义 embedding、自动修复、其他 benchmark 和昂贵黑盒优化仍不属于本阶段。

## 后果与实现门槛

该设计使审计日志、长期事实和可重建摘要边界清楚，也让失败恢复可做逐字节测试。代价
是每代最多增加 `3 + 3E` 次 LLM 调用和 `3E` 次评估，并需要 Stage 4 runner 支持代级
checkpoint。实现前必须先落地 schema/纯转换器/segment store，再接检索和 mutation；
不得先从 trace 临时拼 prompt 后补存储协议。
