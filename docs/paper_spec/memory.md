# Stage 4 可执行记忆规格

本文把 RoCo 的长期反思与记忆引导变异转换成可实现、可测试的状态机。规范来源和
工程补全见 ADR-0004；当本文与 Stage 3 trace 约定冲突时，trace 仍由 ADR-0003 管理，
长期记忆由 ADR-0004 管理。

## 1. 边界与术语

- **Trace**：`roco-collaboration-trace-v1`，代内运行审计，不可直接检索。
- **Provisional event**：从当代 trace/评估派生、尚未带最终选择结果的事件。
- **Committed event**：已回填 Top-N 结果，并由有效 commit marker 覆盖的事件。
- **Role summary**：事件的可重建压缩视图，不是真实事实源。
- **Historical retrieval**：只读取前代已提交事件的确定性 K 条子集。
- **Memory mutation**：以精英、角色摘要和历史证据生成一个新候选。

当前 objective 只允许 `minimize`。所有 schema 使用普通 JSON 类型；禁止 NaN、Infinity、
异常对象、pickle 和依赖平台的随机状态编码。

## 2. 单代状态机

Stage 4 在 Stage 3 单代状态机上增加 M0–M8：

| 状态 | 输入 | 动作 | 输出/失败降级 |
|---|---|---|---|
| M0 Collect | 本代 collaboration trace、EoH 事件、评估 | 提取可归因的 proposal/integrate/失败事实 | provisional events；坏记录隔离 |
| M1 Normalize | provisional events | 规范字段、计算 `delta_g`、稳定 ID 和来源哈希 | 排序后的 `roco-memory-event-v1` |
| M2 Reflect | 本代规范事件、上一代摘要 | E/X/I 各一次 LTReflect | 新摘要；失败则沿用旧摘要或空摘要 |
| M3 Retrieve | 以前代 commit 为界的 event store | 按角色及 3/2 配额检索 K=5 | 有序历史证据；损坏代忽略并报告 |
| M4 Assemble | 精英、摘要、历史事件 | 按优先级构造并确定性截断 prompt | prompt + truncation audit |
| M5 Mutate | 每精英的 E/X/I prompt | 每角色生成一个候选 | 最多 `3E` 个候选；失败安全跳过 |
| M6 Evaluate | mutation 候选 | 既有 AST、spawn、timeout、账本 | 有效分数或结构化失败 |
| M7 Select | 所有本代有效候选及原种群 | 统一确定性 Top-N，回填 selected 标志 | 下一代 population、最终事件 |
| M8 Commit | 最终事件、摘要、population、账本/游标 | segment/checkpoint 后 commit-last | 可恢复的一代；失败不发布半提交代 |

M2 可以概括当代结果供 M5 使用，但 M3 不得读取当代未提交事件。M8 成功后这些事件才
能在下一代成为历史证据。

## 3. Trace 到事件的映射

### 3.1 Explorer/Exploiter

每个 proposal 对应一个事件。`before` 是该分支在 proposal 前最后一个有效候选，
`after` 是 proposal 的有效评估结果。随后的分支 Critic compare 反馈通过
`source_trace_event_ids` 关联到同一事件。若 proposal 无效、timeout 或预算耗尽，仍保留
失败事件，`after_score` 和 `delta_g` 为 null。

### 3.2 Integrator

Integrator 事件的父代是两条最终有效分支；最小化任务的 `before_score` 是父代分数的
最小值。输出有效时计算与该基线的改善。缺少两条有效分支或 Integrator 失败形成失败
事件，不臆造输出候选。

### 3.3 不进入长期事件的 trace 内容

- round 0 初始 Critic：没有干预结果，仅保留在 trace。
- 纯采样、Top-N 排名和预算快照：作为来源/提交元数据，不单独作为角色经验。
- 未与生成动作关联的自由文本：不进入可检索字段。

### 3.4 稳定 ID

将除 `event_id`、墙钟和文件位置之外的规范事件编码为：UTF-8、键排序、紧凑分隔符、
禁止非有限数字的 JSON，然后计算 SHA-256。`event_id` 使用 `mem-` 加摘要前 20 个十六
进制字符。碰撞检测必须比较完整摘要；发生碰撞时 fail closed，不能覆盖。

`sequence` 是转换器按 trace 原始事件顺序分配的整数。最终排序键为
`(generation, round, sequence, event_id)`。

## 4. 成功、失败与改善

```text
comparable = finite(before_score) and finite(after_score)
delta_g = before_score - after_score       # minimize only
success = output candidate valid and evaluation completed with finite score
improved = success and comparable and delta_g > 0
```

`delta_g == 0` 不是 improved。失败类别至少包括 `invalid_output`、`invalid_candidate`、
`evaluation_timeout`、`evaluation_error`、`budget_exhausted`、`provider_error` 和
`summary_error`。failure message 只保留清理后的有限文本；分类不得依赖 message 文案。

## 5. 角色摘要协议

摘要输出必须是结构化对象：

```text
schema_version
role
through_generation
source_event_ids[]
source_hash
prompt_version
provider_name, model_name
useful_strategies[]
failure_patterns[]
applicability_conditions[]
avoid_patterns[]
```

数组元素是有限长度字符串，顺序有意义。摘要请求输入为上一份已提交摘要和本代属于该
角色的规范事件；Integrator 额外接收 Explorer/Exploiter 的新摘要，但只接受上述结构化
字段。Provider 输出必须通过严格 schema 验证。

摘要 LLM 调用次序固定为 Explorer、Exploiter、Integrator。调用前预留 LLM/token 预算，
调用后按实际 usage 提交。任一失败不影响后续角色；Integrator 若缺少某个新摘要则使用
该角色上一份已提交摘要或空摘要。

## 6. K=5 检索算法

对目标 `(benchmark, objective, role)`：

1. 读取 `generation < current_generation` 且 commit/hash 有效的事件。
2. 分成 positive：`success && improved`；negative：其余事件。
3. 各自按排序键降序，先取 positive 3 条、negative 2 条。
4. 若任一类不足，从另一类剩余事件按新到旧补到总数 5。
5. 将选中结果按排序键升序输出，使 prompt 从旧到新阅读。

同一事件不得重复。没有事件时返回空列表，而不是失败。检索过程记录候选计数、选中 ID、
配额补位和被排除损坏代。配置可降低 K，但 `success_slots + failure_slots` 必须等于 K，
均为非负整数；论文默认配置固定为 5/3/2。

## 7. Prompt 组装和截断

每个 memory mutation prompt 的固定 section 顺序为：

1. `contract`：任务、minimize 方向、安全规则、唯一 JSON 输出 schema；
2. `elite`：完整当前精英候选和有限分数；
3. `role_summary`：对应角色摘要；
4. `evidence`：K 条事件的 ID、父/输出候选 ID、前后分数、delta、结果和有限反馈；
5. `instruction`：Explorer/Exploiter/Integrator 视角要求。

外部生成文本（description、feedback、summary）全部作为数据字段 JSON 编码，不可被解释
为更高优先级指令。超限时按 ADR-0004 的优先级处理，并生成：

```text
original_size, final_size, limit
dropped_event_ids[]
truncated_fields[]
reason
```

Mock 使用字符数限制和纯函数截断；真实模型的 tokenizer 接入必须另行版本化。

## 8. Mutation、评估与预算

先按 `(score, candidate_id)` 选择 `elite_count` 个最小化精英，再按精英排名、角色
Explorer → Exploiter → Integrator 顺序执行。每个合法响应只允许一个候选，候选 ID 继续
使用现有稳定候选工厂，并在谱系中记录 elite ID、memory event IDs、summary hash 和角色。

所有候选走与 Stage 3 相同的验证/evaluator。预算在动作发生前检查；被拒绝的动作不调用
provider/evaluator。Provider 已调用但输出非法仍计 LLM calls/tokens；成功解析候选后计
generated candidate；只有有限目标值计 valid evaluation。

设 `E=elite_count`，无失败时每代新增上限：

```text
LLM calls        = 3 + 3E
generated        = 3E
valid evaluations= 3E
```

总调用量还要加 Stage 2 EoH 和 Stage 3 的 `4T+2` 协作调用。任何预算中途耗尽后停止新的
消费动作，已有有效候选仍进入 M7。

V1 不去重也不缓存：相同代码的不同生成事件照常消耗候选与评估预算。

## 9. 代级事务与恢复

### 9.1 工件

事件 segment 每行一个规范 JSON 对象，以换行结尾。摘要和 checkpoint 是单个规范 JSON。
commit marker 包含 schema version、generation、每个工件的相对路径/长度/SHA-256、事件数、
config hash、population IDs 和预算快照。

### 9.2 提交

1. 所有临时文件在目标目录内创建并使用唯一 `.tmp` 后缀。
2. 写入、flush/fsync，然后原子 rename 事件、摘要和 checkpoint。
3. fsync 目录。
4. 最后以相同方式发布 commit marker，并再次 fsync 目录。

已有有效 commit 的代重复提交时，若哈希完全一致则幂等成功；否则报告冲突并停止。

### 9.3 恢复

从 generation 0 起按连续代扫描 commit。第一个缺失/无效 commit 及之后各代都不可见。
最后有效 checkpoint 恢复 population、预算、生成代号、随机流游标和 Mock provider 游标。
临时/孤儿工件只报告，不删除。恢复后重跑半完成代必须产生相同非时间工件哈希。

## 10. 实现顺序与验收矩阵

建议按以下顺序实现，避免存储协议被运行时偶然行为绑死：

1. dataclass/schema、严格 JSON 和 delta/ID 纯函数；
2. trace 转换器及正负事件单测；
3. generation segment store、commit、损坏检测和恢复；
4. 摘要协议与角色感知 Mock；
5. K=5 检索和可审计截断；
6. memory mutation 接入统一验证/评估/Top-N；
7. checkpoint resume 和两代集成 smoke。

最低测试矩阵：schema round-trip；NaN/Infinity 拒绝；minimize delta；稳定 event ID；失败事件；
3/2 检索和补位；角色作用域；摘要失败回退；每精英三角色调用；AST/timeout/provider 失败；
各类预算中断；半写 segment、坏 hash、缺 commit；从 checkpoint 恢复与不停机运行结果一致；
Stage 2 和 Stage 3 两个既有 smoke 完全不回归。

## 11. 明确不在 Stage 4 V1

- 真实 API、网络、密钥和模型性能结论；
- 向量数据库、embedding 或语义相似检索；
- 自动修复、候选重试、内容去重和 evaluation cache；
- 跨 run/global memory，共享用户记忆或长期服务；
- 其他 benchmark、EBBO 或昂贵黑盒优化；
- 最大化 objective（需要新版本契约）。
