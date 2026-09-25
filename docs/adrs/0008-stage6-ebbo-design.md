# ADR-0008：Stage 6 多智能体昂贵黑盒优化设计

- 状态：Accepted；P8 `6efec47` 与 P9a `4189f65970feab0a17299445641916c6245de4a8` 已发布；P9b `fa3b464` 与 P9c `b698649cdf360d56eb063fc257a0e6614a53b733` 已发布；P9c 仅通过离线 Mock 验收
- 日期：2026-09-22
- 基线：`08712c5a065818889b1b11b315dadafee9437d06`
- 上游：ADR-0001、ADR-0003、ADR-0004、ADR-0007、
  `docs/paper_spec/ebbo_design.md`
- 范围：EBBO 的问题、oracle、审计、模块、角色权限、后续评测和实施顺序；P9a 工程选择见第 9 节

## 背景

Stage 2--5 已提供确定性候选、RoCo 角色协作、可选长期记忆、离线 provider 协议和窄范围
COP dry-run，但这些路径优化的是可在本地 evaluator 中求值的启发式代码。Stage 6 的问题不同：
候选 `x` 的目标和约束只能通过一个昂贵 oracle 获得，每次被 oracle 接受的请求都会消耗不可追回的
资源。论文中的 `white-box`/`black-box` 是 prompt 信息可见性条件，不能当作这个昂贵 oracle 黑盒。

现有材料没有证明某个 surrogate、acquisition、benchmark、噪声或并发实现是论文事实，也没有证明
RoCo 在 EBBO 上有效。因此 Stage 6 先冻结概念边界和可测试接口，再由 P9 分步实现。

## 决策

### 1. 最小问题是带可选约束和显式成本的最小化

Stage 6 V1 的规范方向固定为单目标 `minimize f(x)`。候选属于版本化搜索域 `x in X`；零个或多个
约束统一写为 `g_i(x) <= 0`。目标值、约束值、实际 evaluation cost、失败、超时、噪声信息和预算
只能来自 oracle 结果或显式版本化的 Mock 契约，角色文本不得伪造这些值。

oracle 是通过 `OracleRequest`/`OracleResult` 访问的昂贵评估边界。真实实验中的 oracle 可以是仿真、
实验设备或远程服务，但真实昂贵 oracle、真实 API、凭据、网络、付费调用和 benchmark 数据均不在
本设计任务范围内。P9a 只能实现串行、确定性的 Mock expensive-oracle。

JSON-safe 概念契约、字段约束和状态转换由 `docs/paper_spec/ebbo_design.md` 唯一定义。这里的“概念”
表示运行时代码必须保持该语义。P9a 已实现严格、版本化的串行 Mock；P9b 已实现受限离线
角色 Mock；P9c 已发布单进程 fake-async Mock。真实 oracle 与远端异步仍不存在。

### 2. EBBO 使用独立的多维审计账本

每个 EBBO run 独立记录以下不可互换的量：

- `oracle_calls`：oracle 接受的 attempt 数；
- `evaluations_succeeded`：产生合法、有限且可用于目标比较的结果数；
- `evaluations_failed`：已接受但以失败、超时或接受后取消终止的结果数，并按状态细分；
- `candidate_proposals`：通过结构校验进入有限候选池前的结构化候选提案数；
- `llm_calls`、`input_tokens`、`output_tokens`：若角色层使用 LLM 时单独记录；
- `cost_by_source_and_unit`：至少区分 oracle、LLM 和 other，禁止把不同单位或币种隐式相加；未知成本
  另记 attempt，不能以 0 代替；
- `wall_clock_seconds`：单调时钟观察值，不参与可重放哈希。

核心原则是：**一旦 oracle 接受某个 attempt，该 attempt 必须永久计入 `oracle_calls` 和实际成本，
即使它随后超时、失败、返回无效数据、被取消或与既有请求重复。** 发送前拒绝、预算阻止、重复检测
或接受前取消不计 oracle call，但都要留下审计事件。相同 `request_id` 的幂等重放只有在 adapter 能
确认未发生第二次接受时才不重复计数；如果外部系统实际接受了第二个 attempt，就必须给它独立
`attempt_id` 并再次记账。

超时、失败和接受后取消计入 `evaluations_failed` 的相应细分，不可用惩罚值冒充成功观测。重复候选
默认不调用 oracle；若版本化策略明确允许 replicate，则使用不同 replicate index/request ID，按真实
接受次数计费。P9a 不实现 evaluation cache。

本设计不复用、不扩写也不改变 Stage 2--5 `BudgetLedger` 的现有语义。P9a 已在独立
`roco_ebbo.ebbo.ledger.EBBOLedger` 中实现 `ebbo-ledger-v1` 并关闭 G-042；未来桥接或扩展仍须新
schema、迁移/兼容测试和旧 smoke 不变。P9b 在同一独立 ledger 中增补 fake role calls/input/output
synthetic tokens 与可选角色 ceilings；no-role 的 P9a `to_dict`/replay 保持原值，oracle accepted-attempt
记账语义未变。

### 3. 稳定身份、随机性和重放不依赖墙钟

`run_id`、`candidate_id`、`request_id`、`attempt_id`、`observation_id`、候选池 ID 和 posterior
snapshot ID 均由版本化 canonical JSON 的 SHA-256 派生。时间戳、runtime、完成时间和机器信息不得
进入这些 ID、seed 派生、排序 tie-break 或 replay checksum。

所有伪随机流从显式 `root_seed` 经版本化 label 派生；至少分离 Mock oracle、surrogate、candidate
pool、acquisition、四个角色和 scheduler tie-break。记录派生算法、label、输入摘要和结果 seed。
同一串行 Mock 配置必须重放相同候选、请求、结果、观测、posterior 版本和非时间账本。

异步运行只承诺依据已记录的接受/完成事件序列重放决策，不承诺真实完成顺序或 wall-clock 重现。
完成顺序必须显式记录，但不能反向改变已经分配的 ID 或 seed。

### 4. 模块按数据所有权分离

Stage 6 采用以下边界：

1. `oracle adapter`：校验请求、执行接受握手、返回结构化结果；不知道角色或 acquisition；
2. `observation store`：追加请求、attempt、结果和 Observation，提供版本化快照；
3. `surrogate`：只从给定 observation snapshot 拟合/更新共享 posterior；
4. `acquisition`：读取 posterior、搜索域、约束/成本/pending 视图并给候选打分；
5. `candidate pool`：保存有限、去重、带来源和 acquisition 证据的可调度候选；
6. `scheduler`：做预算 reservation、pending 管理、dispatch、完成提交和恢复；
7. `role controller`：把四类角色的结构化建议限制在解释、偏好、审查和调度选择范围；
8. `artifact/reporting`：写 manifest、事件、ledger、snapshot 索引、结果和 replay 审计。

所有角色和所有 acquisition 读取同一个已提交 observation/posterior snapshot。成功、合法的 Observation
可进入目标/约束 surrogate；失败 Observation 保留在事实存储中，只能由明确支持 failure-aware 的组件
消费，不能被静默转成虚构目标值。选择、调度和完成提交的完整数据流见 EBBO 规格。

本 ADR 不指定 GP、神经 surrogate、核、优化器或第三方 BO 库。P9a 第 9 节冻结一个无第三方依赖的
最小工程实现；它不得被倒推为论文事实、通用 BO 推荐或性能已验证能力。

### 5. pending、异步、成本和恢复先设计后实现

调度器在 dispatch 前创建预算 reservation；oracle 明确接受后，reservation 转成不可撤销的
`oracle_calls` 消耗。接受前取消可释放 reservation；接受后只能记录取消请求并等待一个终态，不能退回
call 或已发生费用。pending request 继续占据相应 reservation，并进入 acquisition 的 pending/exclusion
视图，避免无意重复调度。

每个完成结果按 scheduler 实际处理次序获得 `completion_sequence`，共享 posterior 每次只从一个明确
的 observation snapshot 更新。未来并发实现必须记录最大并发数、dispatch 顺序、接受顺序、完成顺序、
reservation 和恢复决定。进程恢复只能从最后一个已提交事件/快照恢复，不能假定 pending 已失败，也
不能对状态未知的请求盲目重发。

成本感知调度只能使用版本化、带单位的预计成本字段，并在结果到达后保存实际成本；不同单位没有显式
换算契约时不可合并。如何建模 pending fantasy、failure、cost 和 late result 均保留为 G-047--G-049，
P9a 只做 `max_concurrency=1` 的确定性 Mock 路径。

### 6. 四角色不能越过统计候选池

Stage 6 的角色定义为：

| 角色 | 允许的职责 | 明确禁止 |
|---|---|---|
| global explorer | 解释全局覆盖、提出区域或探索策略偏好 | 直接构造并发送 oracle 请求 |
| local exploiter | 围绕已观测优良区域提出局部偏好 | 把语言自评分数当目标值 |
| model critic | 审查 posterior 不确定性、校准证据、约束/失败风险和候选排序 | 修改 Observation 或伪造不确定性 |
| resource integrator | 在有限 candidate pool 中按预算、成本、pending 和审查结果选择/排序/调度 | 生成池外候选、绕过预算/约束/重复检测或直接调用 oracle |

角色输出必须是 JSON-safe、可审计的 preference/review/selection 对象。候选只能由
surrogate/acquisition 管线生成并进入有限 candidate pool；resource integrator 只能引用 pool entry ID。
自然语言角色没有 oracle capability，oracle adapter 也不接受角色对象。调度器是唯一可以 dispatch 的
组件，且必须先通过预算、约束和重复检测门。

可复用的 Stage 3 部分是版本化角色身份、结构化输出、provider 失败隔离、事件 trace 和“语言判断不能
代替真实分数”的原则；不可直接复用的是 E/X 候选代码生成、Critic 的前后启发式比较、Integrator 的
代码融合、代/轮调用公式和 TSP evaluator。可复用的 Stage 4 部分是 append-only 事实、稳定 hash、
commit-last、来源可追溯摘要和 fail-closed 恢复原则；不可直接复用的是 `MemoryEvent` schema、K=5
3/2 检索、每精英 E/X/I mutation、字符截断、现有 checkpoint 和“当代摘要驱动 mutation”的运行语义。
任何 memory 接入均晚于 P9b，并作为独立消融与 schema 版本处理。

### 7. 后续评测只冻结比较原则，不宣称已有实现

未来最小单 agent baseline 是：在同一已冻结 surrogate、相同 observation 初始化、candidate-pool 生成、
oracle 预算和 seed 条件下，使用 EI、UCB **或** Thompson sampling 中预注册的一种 acquisition 选择候选。
三者是候选 acquisition，不是当前已实现或已验证功能；若比较多个 acquisition，每个都是单独的 method
cell，不能事后挑最好者充当 baseline。

多 agent 方法必须与 baseline 使用相同 benchmark/version、初始 observations、surrogate contract、
oracle/约束/失败契约、固定 oracle-call ceiling、其他 hard ceilings、seed set 和可见信息。主要指标为
simple regret；cumulative regret、cost-to-target、失败率、wall-clock 和资源消耗只在 reference/target、
失败处理和成本单位预先冻结后报告。不同 benchmark 的 raw score 或 raw regret 不聚合。

预注册消融至少包括：完整角色控制、无角色控制、无 model critic、无 resource integrator、无 memory
（仅在未来确实接入 memory 时）以及不同 acquisition。消融不得通过更大候选池、额外 oracle calls、
不同初始化或额外信息获得隐性预算优势。

没有 ADR-0007 定义的 E4 工件时，不得作性能、显著性、泛化、优越性或论文复现结论。Stage 6 设计
完成本身不产生任何结果证据。

### 8. 后续任务严格按 P9a、P9b、P9c、P10 分离

- **P9a（`4189f65970feab0a17299445641916c6245de4a8` 已发布）**：确定性 Mock expensive-oracle、四个概念数据契约、独立
  Observation/ledger、串行最小 BO baseline；只产生工程控制流证据。
- **P9b（`fa3b464` 已发布）**：四角色控制层和只能引用有限 candidate pool 的 resource-integrator 调度；不增加真实 oracle。
- **P9c（`b698649` 已发布，离线 Mock 已验证）**：单进程 fake-async pending、reservation、取消确认、失败/成本账本、显式恢复和 late-result 审计；不实现真实 worker。
- **P10**：只有用户明确授权 benchmark、来源、许可证、真实 provider/oracle 和硬预算后，才能设计并
  执行真实实验；统计计划也必须在运行前冻结。离线待决字段见
  `docs/paper_spec/p10_experiment_preregistration_template.md`；模板不授权实验。

不得把 P9a 的串行 Mock 实现描述成异步、真实昂贵 oracle 或多智能体效果验证；不得为了加速而合并
这些阶段并越过前置 gap。

### 9. P9a 工程选择冻结

P9a 选择 `ebbo-nearest-observation-surrogate-v1`：对未观测点取一维整数距离最近的成功 Observation
目标值作为 mean，以 `abs(x-x_nearest)/(upper-lower)` 作为 uncertainty；没有成功 Observation 时使用
配置化 finite prior mean。距离并列按 `observation_id` 排序。它没有拟合、校准、概率分布或隐藏
fallback，只为保持 stdlib-only、透明、确定性和可单元测试。

acquisition 固定为 minimization
`ebbo-lower-confidence-bound-v1: score = mean - beta * uncertainty`；分数升序、再按完整 SHA-256
`candidate_id` 升序 tie-break。Mock smoke 使用 `beta=2.0`、pool size `4`。候选来自按 root seed 和
逻辑 iteration 派生顺序的有限整数域，pool 为 immutable tuple，重复提案计 `candidate_proposals` 后
去重。该 LCB 只是 P9a 工程 baseline，不声称等同论文 UCB、已经校准或优于 EI/TS。

Mock problem 固定为 `x in {-5,...,5}`、`f(x)=(x-2)^2+1`、无约束、`noise.kind=none`、默认拒绝重复、
每次 expected/actual cost 为 `1 mock-evaluation-unit`；网络状态为 `unused`，财务成本为 0。它不对应
外部 benchmark、论文数据或真实昂贵 oracle。scheduler 固定 `max_concurrency=1`，adapter 只有持有
scheduler 私有 permit 才能 accept/complete。

canonical JSON 固定为 `roco-ebbo-canonical-json-v1`：UTF-8、Unicode 不转义、object key 词典序、
无多余空白、`allow_nan=false`，读取时拒绝 duplicate keys 和非有限常量。ID 以 contract kind 和该
canonical payload 作 domain separation，保存 `kind-<64 hex SHA-256>`；seed 以同一版本化 envelope
派生 63-bit 非负整数。时间戳和 wall-clock 不进入 ID 或 replay checksum。

P9a smoke 的固定 root seed 为 `9061`，五次串行成功得到 5 oracle calls、5 succeeded、0 failed、
20 candidate proposals、5 `mock-evaluation-unit`、0 LLM calls/tokens、0 财务成本、
`network=unused`。这些是精确工程回归计数，不是 regret、benchmark 或方法性能证据。

### 10. P9b 受限角色 Mock 决策

P9b 新增 `ebbo-role-request-v1`、`ebbo-role-response-v1`、`ebbo-role-audit-v1` 和
`ebbo-restricted-role-control-v1`。请求提供当前有限池的 entry ID、由 Mock 整数域派生的
`negative/zero/positive` region ID、唯一已登记 acquisition strategy ID、只读 mean/uncertainty/
score、已提交 observation ID 列表与稳定 posterior-view ID、剩余 oracle-call 数。角色看不到原始候选
`x`，也没有 oracle permit。相同 iteration 的四角色读取同一已提交 observation/pool snapshot；
后续迭代可因选择不同而形成不同事实历史。这里的 posterior-view ID 不是概率 posterior 声明。

Explorer/Exploiter 只能提交池内 entry/region/strategy ID 和有限非负偏好权重；Critic 必须对每个
池条目给出 uncertainty/constraint/failure/cost 四类风险与 veto 建议；Integrator 只能提交池内
entry ID 的无重复排序与首位选择。未知字段、未知 ID、重复选择、越权候选/score/ledger 字段、非有限
权重或不匹配的请求身份均拒绝。`veto_mode=advisory` 只审计建议；`hard` 将有效 veto 条目排除，
若全部被 veto 则不 dispatch。无效响应、provider error/timeout 或角色调用/token ceiling 耗尽均写
结构化审计，退回 P9a acquisition 排序；有效 hard veto 仍在 fallback 中生效。

provider 只能显式注入 `ebbo-deterministic-fake-role-provider-v1`，无 LLM/HTTP/密钥/网络。
`llm_calls` 在此仅记录 fake role invocation，tokens 是 UTF-8 字节数向上按四字节分组的合成
计数，不是实际 tokenizer 或计费量，财务成本为 0；两者绝不折算为 oracle calls。P9b 的
`RestrictedRoleScheduler` 在未改动的 P9a `SerialScheduler.dispatch` 前复核原 pool hash/顺序、
entry membership、duplicate、Mock `none-v1` 约束/域与预算；角色不能直接 dispatch。异步、真实
约束、真实成本感知和 memory 仍留给 P9c/P10 或新 gap。

四路径 `full/no_roles/no_critic/no_integrator` 共用 P9a Mock oracle、搜索域、root seed 9061、
空初始事实、候选池规则和 5-call ceiling。每路径为 5 oracle calls、5 success、20 proposals、
5 Mock cost、0 财务成本、`network=unused`；fake role calls 分别 20/0/15/15。no_roles
直接执行 P9a baseline，replay checksum 保持
`7d4b4da802d2cd4e29742b74fa9e3866b4ab319a27d207e1ce4c8e79fac5da01`。
这只是离线控制流/权限/重放证据，不是性能比较或多智能体优越性证据。

## 后果

该决策使昂贵 oracle 的不可追回消耗、语言角色的权限和 posterior/candidate-pool 的统计边界可审计，
并为串行 Mock 到异步真实实验提供分层路径。P9a/P9b 只产生串行工程 Mock 控制流证据；
P9c 只产生 fake-async 状态/恢复证据，不产生性能数字、多智能体效果或真实 provider 能力。
真实 benchmark/noise/constraints/cost、远端并发、memory 和统计仍须以后用证据和测试逐项关闭。

### 11. P9c 离线异步 Mock 决策（实现前冻结）

P9c 独立启用 `ebbo-async-mock-scheduler-v1`；P9a/P9b 默认串行路径与已有 replay 不变。
显式 `max_concurrency` 限制 reserved 加 accepted 的 outstanding 数量。reservation 预占
未来 call 和同单位预计成本；oracle 接受后 call 立即永久增加，预计成本继续作为 pending
hold，直到实际成本结算。准入使用 `known_cost + 所有 outstanding expected cost`；实际
超额照实记账并停止新发送，未知实际成本不当作零。失败候选也排除重发，失败观测不进入
目标 surrogate。P9c 的成本/失败感知仅限准入和事实保留，不实现概率模型或 cost-aware
acquisition。

完成顺序由版本化本地 Mock completion script 明确给定，同批回调按 request ID 排序。
接受前取消释放 reservation、不计 call；接受后先记 `cancel_requested`，仅 Mock 确认取消
才按已确认实际成本形成 `cancelled_after_accept` 失败 Observation；若结果先到则结果赢得
终态。终态之后的重复/迟到结果只追加审计，不二次结算或覆盖事实。P9c 在现有严格
OracleResult/Observation v1 枚举内增补取消后终态校验，旧结果和 replay 保持不变。

checkpoint 只在完整状态转换及 append-only 事实落盘后 commit-last 原子替换。显式 resume
核验 schema、config/run 身份、checkpoint SHA-256、store 字节摘要和 ledger/pending/结果
交叉不变量；损坏、孤儿尾部或状态不明一律 fail closed，不截断或重发。恢复已接受的本地
Mock pending 只重建确定性 handle，不再次调用 accept。仅承诺相同 completion script 的
显式边界中断恢复与不中断运行非时间等价；真实远端 reconciliation、任意指令点 crash
恢复及真实成本调度仍开放。

P9c Mock 恢复与预算边界已由独立单元/集成测试覆盖；实际成本超预计仍如实入账，
可能使 `known_cost` 超过准入 ceiling，但不得退款，之后不再准入新请求并先排空既有 pending。
本节不授予真实远端 exactly-once 或任意指令点 crash consistency 保证。

P9c 本地完整门禁还包括 221 passed/1 skipped、Ruff check/format、mypy、doctor、
Stage 2/3/4 和 P9a/P9b/P9c 六条 CLI smoke、`git diff --check`；这些不是 E4 证据。

仅已接受且已有终态的重复/迟到完成回调标记为 `late_result`；从未被 oracle 接受的
reservation、接受前取消或未知 request 的完成回调是结构化拒绝，不能冒充 late result。
非法状态下的 accept、completion 和 cancel acknowledgement 也留下拒绝审计且不计 call。
