# Stage 6 多智能体昂贵黑盒优化可执行设计规格

## 0. 状态、范围与术语

本文冻结 Stage 6 EBBO 的概念接口和后续验收边界。状态是：**P8 设计已发布；P9a 串行工程 Mock
已在工作树离线验证，尚未提交/发布；P9b/P9c/P10 未开始**。本文不是 RoCo 论文事实的延伸，不表示
GP、概率校准、异步 worker、真实 benchmark、真实昂贵 oracle 或性能实验已经存在。ADR-0008 记录
决策理由；本文件同时记录 P9a 已冻结的工程子集。

必须区分两种 black-box：

- 论文的 black-box prompt：不向 LLM 暴露某些问题内部语义的信息可见性条件；
- EBBO black-box：目标与约束反馈只能通过昂贵 oracle 获得。

二者没有自动对应关系。prompt 可见性不得改变 oracle 计费语义，oracle 也不授予角色访问真实 API 的
能力。

本文中的 JSON-safe 值只允许 `null`、布尔、字符串、整数、有限浮点数、上述值组成的数组，以及键为
字符串的对象。禁止 NaN、Infinity、bytes、tuple、set、异常对象、类实例和未版本化的 pickle。
P9a canonical JSON 版本为 `roco-ebbo-canonical-json-v1`：UTF-8、`ensure_ascii=false`、object key
词典序、紧凑分隔符、`allow_nan=false`；读取时用 duplicate-key hook 和 non-finite constant hook
fail closed。哈希 envelope 显式包含 canonical version、kind 和 payload，输出 `kind-<64 hex SHA-256>`。
这关闭 G-042 的 P9a canonicalization/ID 子项；它不是跨语言 RFC canonical JSON 声明。

## 1. 最小问题契约

一个 EBBO problem 至少声明：

```text
problem_id, problem_version
search_space_contract
objective { direction = "minimize", name, unit | null }
constraints[] { constraint_id, convention = "g_i(x) <= 0", unit | null }
oracle_contract_version
noise_contract
evaluation_cost_contract
timeout_scope
```

`search_space_contract` 必须能确定性校验和 canonicalize 候选。V1 只允许一个待最小化的标量 primary
objective；多目标或 maximize 需新版本。约束可为空。没有成功 oracle result 时，任何模块都不得补写
objective/constraint。已知噪声、未知噪声、heteroscedastic noise、replicate 策略及聚合方式均不得由
实现暗定；P9a 的 deterministic Mock 明确使用 `noise_contract.kind="none"`。

P9a `ebbo-mock-integer-space-v1` 是工程 fixture：`x` 为闭区间 `[-5,5]` 的单个整数，
`ebbo-mock-expensive-oracle-v1` 返回 `f(x)=(x-2)^2+1`，constraints disabled，默认不允许 replicate。
它不对应任何外部 benchmark 或论文函数。

evaluation cost 可以是固定、候选相关或结果后确认，但必须用非负有限数和显式 unit 表达。USD、秒、
设备小时与抽象 oracle-unit 不能隐式相加。wall-clock 是独立观察量，不等同于 evaluation cost。
P9a 固定 expected/actual cost 为 `1 mock-evaluation-unit`，source 为
`ebbo-mock-fixed-cost-v1`；财务成本另记为 0，不能把抽象 cost 写成 USD。

## 2. JSON-safe 概念契约

### 2.1 `EvaluationStatus`

允许值及状态语义：

| 值 | 终态 | oracle call | evaluation 结果 |
|---|---:|---:|---|
| `reserved` | 否 | 未发生 | 预算已预留，尚未被 oracle 接受 |
| `accepted` | 否 | 已消耗 | oracle 已接受；必须计费/计 call |
| `cancel_requested` | 否 | 已消耗 | 接受后请求取消，结果仍未知 |
| `succeeded` | 是 | 已消耗 | 返回合法有限 objective，并满足结果 schema |
| `failed` | 是 | 已消耗 | accepted 后 oracle/runtime/schema 失败，无可比较 objective |
| `timed_out` | 是 | 已消耗 | accepted 后达到版本化 timeout scope，无可比较 objective |
| `cancelled_before_accept` | 是 | 未发生 | 可释放 reservation，仍保留事件 |
| `cancelled_after_accept` | 是 | 已消耗 | 不退还 call 或实际成本，记失败 evaluation |

合法主路径为 `reserved -> accepted -> succeeded|failed|timed_out`；取消路径为
`reserved -> cancelled_before_accept` 或
`accepted -> cancel_requested -> succeeded|failed|timed_out|cancelled_after_accept`。
adapter 若在一次原子动作中接受并完成，可连续写入 accepted 和终态事件，不能省略 accepted 记账点。
终态之后到达的回调作为 `late_result` audit event 追加，不覆盖既有 Observation；未来是否采纳 late
result 由 G-048 的新策略决定。

### 2.2 `OracleRequest`

```json
{
  "schema_version": "ebbo-oracle-request-v1",
  "request_id": "request-<64 hex>",
  "run_id": "run-<64 hex>",
  "problem_id": "...",
  "problem_version": "mock-quadratic-engineering-v1",
  "oracle_contract_version": "ebbo-mock-expensive-oracle-v1",
  "candidate_id": "candidate-<64 hex>",
  "candidate": {"x": 0},
  "objective_direction": "minimize",
  "constraint_contract": {"enabled": false, "version": "none-v1"},
  "logical_evaluation_index": 0,
  "replicate_index": 0,
  "oracle_seed": 0,
  "timeout_seconds": 1.0,
  "seed_lineage": {
    "root_seed": 9061,
    "request_index": 0,
    "candidate_seed": 0,
    "oracle_seed": 0
  },
  "budget_reservation": {
    "expected_cost": 1.0,
    "cost_unit": "mock-evaluation-unit",
    "cost_source": "ebbo-mock-fixed-cost-v1",
    "oracle_calls": 1
  },
  "reservation_id": "reservation-<64 hex>",
  "deduplication_key": "deduplication-<64 hex>",
  "provenance": {
    "candidate_pool_id": "pool-<64 hex>",
    "acquisition_contract": "ebbo-lower-confidence-bound-v1",
    "scheduler": "ebbo-serial-scheduler-v1"
  },
  "created_at_utc": null
}
```

字段规则：

- `candidate` 必须先由 search-space contract canonicalize；角色自由文本不得进入此字段；
- `logical_evaluation_index` 在 reservation 时单调分配，不使用完成顺序；
- 不需要随机性的 oracle 使用 `oracle_seed=null`，不能用系统时间填充；
- `timeout_seconds` 的作用域由 problem contract 定义；
- `budget_reservation.expected_cost` 是调度依据，不代替实际结果成本；未知时用 `null`，不能填 0；
- `request_id` 哈希 request identity 字段但排除时间、runtime 和可变传输元数据；
- `replicate_index>0` 必须由已冻结的噪声/replication 策略授权，否则视为重复。

真实传输 endpoint、credential、header 或 secret 不属于 OracleRequest，也不得进入工件。

### 2.3 `OracleResult`

```json
{
  "schema_version": "ebbo-oracle-result-v1",
  "result_id": "result-<64 hex>",
  "request_id": "request-<64 hex>",
  "attempt_id": "attempt-<64 hex>",
  "status": "succeeded",
  "objective": 0.0,
  "constraints": null,
  "feasible": null,
  "failure": null,
  "actual_cost": {
    "amount": 1.0,
    "unit": "mock-evaluation-unit",
    "source": "ebbo-mock-fixed-cost-v1"
  },
  "noise": {"kind": "none"},
  "oracle_metadata": {
    "adapter_version": "ebbo-mock-expensive-oracle-v1",
    "network": "unused"
  },
  "started_at_utc": null,
  "completed_at_utc": null
}
```

字段规则：

- `status` 在 OracleResult 中必须是终态；
- `succeeded` 要求 finite objective、与 problem contract 完全一致的 constraint keys、可判定 feasibility
  和合法 actual cost；
- 非成功结果的 `objective`、`constraints` 和 `feasible` 为 `null`，不得保存惩罚值；
- `failure` 为 `null` 或 `{phase, type, safe_message, retryable}`，不得回显密钥、原始上游正文或异常对象；
- accepted attempt 的 usage/cost 信息即使不完整也要保存可确认部分；`actual_cost` 未知时为 `null`，
  不得伪装成 0；
- P9a 的 `started_at_utc`/`completed_at_utc` 是可空审计值，不参与 result identity 或 replay checksum；
  wall-clock 只进入独立 ledger；
- transport retry 若再次被接受，必须使用新的 `attempt_id`、增加 `oracle_calls`，并与同一 request 的
  attempt history 关联。

### 2.4 `Observation`

```json
{
  "schema_version": "ebbo-observation-v1",
  "observation_id": "observation-<64 hex>",
  "run_id": "run-<64 hex>",
  "request_id": "request-<64 hex>",
  "attempt_id": "attempt-<64 hex>",
  "result_id": "result-<64 hex>",
  "candidate_id": "candidate-<64 hex>",
  "candidate": {"x": 0},
  "status": "succeeded",
  "objective": 0.0,
  "constraints": null,
  "feasible": null,
  "failure": null,
  "actual_cost": {
    "amount": 1.0,
    "unit": "mock-evaluation-unit",
    "source": "ebbo-mock-fixed-cost-v1"
  },
  "noise": {"kind": "none"},
  "logical_evaluation_index": 0,
  "completion_sequence": 0,
  "eligible_for_objective_surrogate": true,
  "source_result_hash": "result-<64 hex>",
  "seed_lineage": {},
  "oracle_metadata": {},
  "observed_at_utc": null
}
```

Observation 是 request/result 的不可变、可审计合并事实。只有 `succeeded` 且通过 problem/result 校验的
Observation 才可令 `eligible_for_objective_surrogate=true`。失败 Observation 仍进入 store，但 objective/
constraints 保持 null。`completion_sequence` 记录 scheduler 处理完成事件的实际顺序；它不参与 ID、
seed 或候选 tie-break。`observed_at_utc` 同样是非重放审计值。重复、replicate 和 late result 通过独立
audit fields/events 关联，不覆盖旧事实。

## 3. 独立预算与审计契约

### 3.1 run ledger

概念 schema `ebbo-ledger-v1` 至少包含：

```text
oracle_calls
evaluations_succeeded
evaluations_failed
evaluation_failures_by_status { failed, timed_out, cancelled_after_accept }
candidate_proposals
llm_calls
input_tokens
output_tokens
cost_by_source_and_unit[] { source = oracle|llm|other, unit, amount }
unknown_cost_attempt_ids[]
wall_clock_seconds
reservations { active, released, committed }
hard_limits
reached_limits[]
```

所有离散 counter 单调不减。`wall_clock_seconds` 来自 monotonic clock，可在恢复后分 segment 累加，但不
参与 replay checksum。预算判断必须发生在新消费动作之前；达到任一 hard limit 后不创建新的
reservation，不影响已接受 work 的结算。预计成本只用于 admission；实际成本可令账本超过 ceiling，
超出部分必须如实记录并阻止后续工作。有 cost hard limit 时，admission 必须有同单位的保守 cost upper
bound；accepted 后 actual cost 仍未知时，将 attempt 加入 `unknown_cost_attempt_ids` 并停止新的同类成本
动作，不能以 0 继续运行。

`candidate_proposals` 在一个结构化候选通过 search-space 校验并被提交给 candidate-pool admission 时
增加；重复检测随后发生，因此重复提案仍可审计，但不自动产生 oracle call。pool 中另报 unique entries、
rejected duplicates 和 rejection reason，不能把它们混成 oracle evaluations。

### 3.2 请求、重复、取消与恢复

- **发送前预算拒绝**：写 `budget_rejected`，无 reservation、call 或 evaluation；
- **reservation 后接受前取消**：写 `cancelled_before_accept`，释放 reservation，无 oracle call；
- **accepted 后失败/超时/取消**：call 永久保留，终态计入 failed evaluation；
- **同 request ID 幂等重放**：adapter 确认未二次接受时不重复计 call；状态未知时 fail closed，不盲重发；
- **同 candidate duplicate**：默认在 dispatch 前拒绝；有版本化 replicate policy 时使用新 request；
- **late result**：追加事件，不改写终态，不在未冻结策略下更新 surrogate；
- **进程恢复**：从最后已提交 ledger/event/store snapshot 恢复，对 active reservation 做 reconciliation，
  不假定“本地没结果”等于“oracle 未接受”。

P9a 需要测试每条规则。P9c 才实现并发 reconciliation、取消和 late-result 路径。

### 3.3 稳定 ID、seed 和 replay

P9a 已冻结的稳定派生关系如下；全部使用 `roco-ebbo-canonical-json-v1` domain envelope：

```text
run_id = H(run-contract-version, complete strict config snapshot)
candidate_id = H(search-space-contract, canonical candidate)
candidate_pool_id = H(sorted unique entries, proposal/duplicate counts)
reservation_id = H(run_id, logical evaluation index, candidate_id, reservation)
request_id = H(all semantic request fields excluding created_at_utc)
attempt_id = H(adapter version, request_id, attempt index)
result_id = H(canonical semantic terminal result excluding timestamps)
observation_id = H(request/result fact excluding completion_sequence and observed_at_utc)
derived_seed = H(root_seed, ordered component labels and stable logical inputs), truncated to 63 bits
```

可重放字段包括 contracts/config hashes、候选与 pool、request/result/observation、logical indexes、事件顺序、
derived seeds、posterior input snapshot IDs、acquisition scores/排序、ledger 离散 counter 和 cost。不可要求
逐字节重放的字段包括 wall-clock、时间戳、PID、host、线程 ID、真实网络延迟和真实异步完成时间；这些
字段在 replay checksum 中规范为 null 或排除，但原始审计值仍保存。

## 4. 模块边界与数据流

### 4.1 接口职责

| 模块 | 输入 | 输出/所有权 | 不得做 |
|---|---|---|---|
| oracle adapter | 已准入 OracleRequest | accepted/terminal events、OracleResult | 看角色 prompt、选候选、绕过账本 |
| observation store | request/attempt/result events | append-only Observation 与 snapshot ID | 拟合模型、覆盖历史、伪造失败分数 |
| surrogate | committed observation snapshot | posterior snapshot、fit audit | 调 oracle、选择最终调度项 |
| acquisition | posterior、domain、pending、cost/constraint contract | 分数和生成证据 | 直接 dispatch、隐藏候选 |
| candidate pool | canonical candidates + acquisition evidence | 有限 pool、去重/rejection audit | 接受池外 integrator 选择 |
| scheduler | pool selection、ledger、pending | reservation、dispatch、completion commit | 让角色直连 oracle、超预算发送 |
| role controller | 同一 snapshot、pool、预算摘要 | preferences、reviews、pool-entry selections | 写 Observation、生成真值、池外请求 |
| artifact/reporting | 所有已提交事实/版本 | manifest、events、ledger、reports | 把缺失结果变成性能结论 |

### 4.2 串行 V1 数据流

```text
committed Observations
  -> fit/update surrogate
  -> immutable posterior snapshot
  -> acquisition proposes/scores canonical candidates
  -> finite candidate pool + dedup/constraint precheck
  -> optional role review/selection (P9b; absent in P9a)
  -> scheduler budget admission + reservation
  -> oracle adapter accepted event (oracle_calls += 1)
  -> terminal OracleResult
  -> append Observation + settle ledger
  -> next posterior snapshot
```

P9a 每次最多一个 pending evaluation。若没有可调度候选、预算不足或所有候选被拒绝，run 以结构化
终态停止，不能让角色生成一个池外候选“救场”。

### 4.3 pending 与异步扩展

P9c 可以把多个 reservation/accepted request 放入 pending set，但必须满足：

1. `max_concurrency` 和每一维预算在 dispatch 前检查并预留；
2. acquisition 获取版本化 pending view；采用 exclusion、fantasy、penalization 或其他方法前先关闭 G-048；
3. scheduler 按收到并处理的顺序写 `completion_sequence`，同一批事件以 request ID 作稳定 tie-break；
4. 每次决策引用唯一 committed observation/posterior snapshot，不能读半提交结果；
5. 失败结果不进入 objective surrogate，除非另有明确的 failure model；
6. 恢复时先 reconciliation 所有 active request，再决定等待、取消或标记 unknown；
7. 实际完成顺序影响在线决策时，必须把该顺序视为 run 输入工件，而非声称仅凭 seed 可重建现实时间。

## 5. surrogate、acquisition 与共享 posterior

所有 agent 共享同一个由 committed Observation snapshot 派生的 posterior；不存在每个语言角色私有的
“真值模型”。posterior artifact 至少记录 surrogate contract/version、训练 observation IDs、超参数来源、
fit seed、数值状态、失败/降级和 snapshot hash。fit 失败必须结构化停止或使用事先版本化的 fallback，
不能静默更换模型。

acquisition artifact 至少记录 contract/version、posterior snapshot、pending snapshot、约束/成本处理、
随机 seed、raw score、方向、tie-break 和候选生成过程。P9a 已选择透明的工程子集：

- `ebbo-nearest-observation-surrogate-v1`：mean 为一维整数域内距离最近的成功 Observation 目标值，
  uncertainty 为距离除以域直径；距离并列按 observation ID，cold start 使用配置化 finite prior mean；
- `ebbo-lower-confidence-bound-v1`：minimization score 为 `mean - beta * uncertainty`；
- 候选先按 `derive_seed(root_seed, "candidate-order", iteration, candidate_id)` 排序取有限 pool，再按
  acquisition score 升序、完整 candidate ID 升序决定调度顺序；
- Mock smoke 固定 `prior_mean=10.0`、`beta=2.0`、pool size `4`，不使用第三方库。

该 surrogate 不提供概率 posterior、校准或拟合；“posterior”工件仅是成功样本的确定性共享快照。
EI、论文意义的 UCB、Thompson sampling、GP/神经 surrogate 和其他 pool optimizer 仍是未来候选，
不得将 P9a LCB 写成已验证 BO 方法或性能结论。G-043/G-044 的 P9a 工程子项已关闭，未来比较仍开放。

candidate pool 必须有限且不可变，概念字段至少包括：

```text
candidate_pool_id, pool_generation_index, posterior_snapshot_id
entries[] {
  pool_entry_id, candidate_id, candidate, acquisition_contract,
  acquisition_score, predicted_objective_summary,
  predicted_constraint_summary | null, expected_cost | null,
  pending_or_duplicate_status, generation_provenance
}
rejections[] { candidate_id | null, reason, provenance }
```

角色只能引用这些 entry；role output 不能覆盖 acquisition score 或预测字段。

## 6. 多角色受限协议

四角色都读取同一份：problem contract、committed observation summary、posterior audit、有限 pool、pending
和剩余预算。global/local 所称“区域”只能引用 candidate pool 已登记的 region/cluster ID 或 pool entry
集合，所称“策略”只能引用 acquisition artifact 已登记的策略 ID；不得输出一个原始 `x` 并把它伪装成
偏好。角色可以输出：

- global explorer：pool/区域的探索优先级与理由；
- local exploiter：已观测优良邻域的利用优先级与理由；
- model critic：不确定性/校准/约束/失败/成本证据的 review、warning 或 veto 建议；
- resource integrator：只由 `pool_entry_id[]` 构成的排序/批次选择及预算理由。

role controller 必须对未知字段、未知 pool ID、重复选择、超 batch size、非有限权重和越权动作 fail
closed。critic 的 veto 是否具有硬约束效力必须配置化；无 integrator 消融使用预注册的确定性 acquisition
排序，不允许另一个隐藏语言角色替代。最终 admission 始终由 scheduler 再校验，因而角色建议不能绕过
预算、约束、pending 或 duplicate gate。

Stage 3 可复用 role/provider/audit 设计原则，但不能直接复用“生成启发式代码”的 response schema。
Stage 4 memory 若未来接入，只能总结已提交 Observation/decision 事实并带来源 ID；当前 memory schema、
K=5 检索和三角色 mutation 不适用于 EBBO。P9b 默认无跨 run memory。

## 7. 后续评测协议

### 7.1 baseline 与多 agent 对照

单 agent baseline 使用与多 agent 方法完全相同的 problem、初始 observation design、surrogate、candidate
generator、pool size、oracle、约束、failure/noise/cost contract、seed set 和 hard budgets。唯一方法差异
是候选选择控制：baseline 由预注册的 EI、UCB 或 Thompson sampling 直接按确定性 tie-break 从 pool
选取；多 agent 由受限角色控制层在同一 pool 内选择。每种 acquisition 若都运行，必须分别报告。

公平性的主要资源轴是固定 `oracle_calls` ceiling；同时固定并报告成功/失败 evaluations、候选提案、
LLM calls/tokens、cost 和 wall-clock ceilings/actuals。多 agent 不可用额外 oracle calls、隐藏初始数据、
更大 pool 或不同 surrogate。角色层的 LLM 消耗不能折算成 oracle calls，必须另账报告。

### 7.2 指标

- `simple_regret(b) = best_feasible_observed_value_by_budget_b - reference_optimum`；只有可靠 reference 和
  minimize contract 时定义；
- `cumulative_regret(b)`：按 oracle acceptance 的逻辑 evaluation 顺序累计 instant regret；噪声下使用
  latent/observed value、失败如何处理必须预注册，否则不报告；
- `cost_to_target`：首次获得达到预注册 target 的成功可行 Observation 时累计的 oracle cost、calls 和
  wall-clock；未达到者按 censored/failure 规则报告，不伪造数值；
- `failure_rate`：failed evaluations / accepted oracle calls，并按 failed/timeout/cancelled 细分；
- 时间指标：end-to-end wall-clock、oracle busy time、scheduler overhead（若可测）和 time-to-target；
- 资源指标：所有 ledger actuals、budget reached 和 pending/concurrency 摘要。

无 reference optimum 时可报告 best-so-far objective，但不得称 simple regret。约束问题只在可行成功
Observation 中更新 best；“尚无可行点”的表示必须预注册。跨 benchmark 不聚合 raw score、raw regret
或未经预注册归一化的 cost。

### 7.3 消融矩阵

| Cell | 角色控制 | model critic | resource integrator | memory | acquisition |
|---|---|---|---|---|---|
| 单 agent baseline | 无 | 无 | 无；固定 acquisition 排序 | 无 | 预注册 EI/UCB/TS 之一 |
| 完整多 agent | global + local | 有 | 有，限 pool | 默认无；未来可开 | 与 baseline 相同 |
| 无角色控制 | 无 | 无 | 无 | 与主 cell 一致 | 与主 cell 相同 |
| 无 model critic | global + local | 无 | 有，限 pool | 与主 cell 一致 | 与主 cell 相同 |
| 无 resource integrator | global + local 的审计建议不参与最终选择 | 可有 | 无；固定 acquisition 排序 | 与主 cell 一致 | 与主 cell 相同 |
| 无 memory | 与完整方法相同 | 与完整方法相同 | 与完整方法相同 | 无 | 与主 cell 相同 |
| acquisition variants | 固定所选控制层 | 固定 | 固定 | 固定 | EI、UCB、TS 分别成 cell |

只有未来确实实现 memory 后才运行/解释“无 memory”。所有 cell 必须固定 oracle-call budget 和其他公平
条件。没有 E4 工件不得作性能、显著性、泛化或优越性结论；遵循 ADR-0007 的失败保留和预注册原则。

## 8. 工件和验收设计

P9a Mock smoke 当前产生：

```text
manifest.json
audit.jsonl
requests.jsonl
results.jsonl
observations.jsonl
ledger.json
posterior.json
candidate_pools.jsonl
replay.json
summary.json
```

`audit.jsonl` 与 `observations.jsonl` 逐记录 append，重开时严格重读 schema、ID 和连续 sequence；snapshot
记录两条流的 SHA-256。P9a 没有 crash reconciliation、commit marker、async pending 或 resume，这些属于
P9c。其余文件在新 output directory 内一次性写入。工件包含 contract/version、root/derived seeds、预算、
失败和非时间 replay checksum；敏感 endpoint、credential、raw secret 或未脱敏上游正文不得进入工件。

P9a 已测试合法成功、发送前预算拒绝、accepted 后失败/timeout、接受前取消、重复候选、空 pool、非法/
非有限 result、实际成本超 ceiling、未知成本、稳定 ID/seed、append/reopen/snapshot、串行 replay、有限/
immutable/deduplicated pool、tie-break 和 scheduler-only dispatch。P9a 没启用约束，因此没有虚构约束成功
测试。Stage 2--5 旧 smoke/ledger 作为回归不变量。P9b 增加所有角色越权、未知 pool ID、critic/integrator
失败及消融降级。P9c 增加 commit-last/crash recovery、超额 reservation 防护、乱序完成、取消竞态、
unknown pending 恢复、late result 和 failure-aware 调度。

## 9. 分阶段实施边界

### P9a：串行最小 baseline

**已在当前工作树实现并离线验证，尚未提交/发布。** 包括 deterministic Mock expensive-oracle、
`EvaluationStatus`/`OracleRequest`/`OracleResult`/`Observation`、独立 ledger/store、有限 candidate pool、
第 5 节的 surrogate/LCB 和 `max_concurrency=1` scheduler。Mock domain 为整数 `[-5,5]`，objective 为
`(x-2)^2+1`，无约束、无噪声，固定成本 `1 mock-evaluation-unit`。不得接角色控制、真实网络、真实数据、
异步 worker 或性能声明。

### P9b：受限角色控制

实现 global explorer、local exploiter、model critic、resource integrator 的结构化控制层。Integrator
只能引用 P9a candidate pool；scheduler 仍是唯一 dispatch capability。保持同 surrogate/acquisition 的
单 agent baseline 和角色消融入口。不得调用真实 oracle。

### P9c：异步与失败恢复

实现多 reservation、pending view、乱序 completion、failure-aware/cost-aware scheduling、取消、late
result、reconciliation 和 crash recovery。所有策略必须先关闭 G-047--G-049，且串行模式保持回归。

### P10：受授权真实实验

只有用户逐项明确授权 benchmark/source/license、真实 provider/oracle、凭据处理方式、硬预算、统计
计划和结论范围后才可开始。P10 不由 Stage 6 设计或任何 Mock 测试自动授权。

## 10. 已关闭的 P9a 子项与仍开放内容

G-042 已由独立 ledger/canonical JSON/ID/seed 代码和旧回归关闭。G-043--G-049 只关闭 P9a 所需子项：
deterministic nearest-observation surrogate、LCB/pool/tie-break、Mock function/domain、no-noise/no-replicate、
失败事实且 constraints disabled、serial scheduler，以及固定 Mock cost unit/unknown-overrun 审计。

以下仍开放且不得暗定：真实/通用 surrogate 与 acquisition 比较，外部 benchmark/reference，真实噪声和
replication，约束与 failure-aware 模型，async pending/concurrency/recovery/late result，真实成本与
cost-aware acquisition（G-043--G-049 的后续子项）；全部指标/target/重复数/统计问题 G-050；四角色和
可选 memory G-051。参数表中的 `unset` 是有意状态，不是库缺省值。
