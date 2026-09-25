# P10 EBBO 授权决策与实验预注册模板（离线草案）

> 状态：`template-only`；不是已批准方案、已预注册实验或真实运行授权。本文不选择 benchmark、
> oracle、LLM provider、预算或统计 target；所有待决值保持 `unset`。填写后仍须逐项取得用户明确授权，
> 再以新版本冻结；不得从 P9 Mock 或 Stage 5 工程 profile 继承数值。

## 1. 依据与已冻结事实

- [ADR-0008](../adrs/0008-stage6-ebbo-design.md) 与 [EBBO 规格](ebbo_design.md) 冻结
  V1 单一 `minimize` objective、可选 `g_i(x) <= 0` 约束、严格 JSON-safe request/result/
  Observation、scheduler-only dispatch 和 accepted attempt 永久计入 `oracle_calls` 的原则。
- P9a/P9b/P9c 仅是离线工程 Mock：P9c 的单进程 fake-async、合成成本和可重放 checksum 不证明
  真实远端 exactly-once、真实费用、方法性能或论文复现。Stage 2–5 `BudgetLedger` 不参与 EBBO 结算。
- [ADR-0007](../adrs/0007-stage5-multicop-statistics-evidence.md) 的 E0–E4 证据分级和
  [多 COP 协议](multicop_experiment_protocol.md) 的失败保留、匹配 seed 与统计闸门适用于
  未来比较；P10 仍需专属 EBBO 协议版本和单独授权。
- EI/UCB/Thompson sampling、真实 surrogate、benchmark、噪声模型、约束模型、成本感知 acquisition、
  真实 provider 和 memory 均未由 P9 验证为 P10 方法。`unset` 不表示采用库默认值。

## 2. 授权记录（每个闸门独立决定）

| 字段 | 当前值 | 所需证据/决定 |
|---|---|---|
| `preregistration.protocol_id` / `version` / `hash` / `freeze_at` | `unset` / `unset` / `unset` / `unset` | 运行前冻结不可变协议及时间，不以本模板冒充完成预注册 |
| `authorization.owner` / `approved_at` | `unset` / `unset` | 由用户明确给出批准人、日期及精确范围 |
| `authorization.e2_source_and_license` | `unset` | 明确可访问来源、允许用途、许可证和获取范围；本模板不授权下载 |
| `authorization.e3_offline_adaptation` | `unset` | 指定离线 parser/evaluator、Mock dry-run 和数据范围；与 E2 分开批准 |
| `authorization.e4_real_experiment` | `unset` | 在完整预注册、真实 oracle/provider 与硬预算获批后单独授权 |
| `authorization.credential_handling` | `unset` | 明确安全注入、脱敏、权限和撤销方式；不得把密钥写入本文或工件 |
| `authorization.claim_scope` | `unset` | 指定允许报告的精确 benchmark/version/cell；不自动允许泛化或论文复现 |

任何必需授权仍为 `unset` 时，不得执行相应阶段。批准记录必须引用不可变的协议版本或摘要；
撤销、变更范围或增预算必须形成新记录，不能追改已完成 run。

## 3. 待用户决定的实验字段

| 主题 | 待填字段（当前均为 `unset`） | 阻断条件与对应 gap |
|---|---|---|
| Benchmark 与来源 | `benchmark_id`、`version/release`、`source_id/URL`、`license_id`、允许用途、获取范围 | 未经来源/许可授权不得下载；G-045 |
| 数据与 split | `inventory`、逐实例/总 SHA-256、`split_policy_version`、train/validation/test 清单、等价实例防泄漏规则 | 无可信 checksum/split 不得进入 E3 或 test |
| Reference | `reference_value`、方向、来源/验证级别、实例对应版本 | 无可靠 reference 不得称 simple regret；G-045/G-050 |
| 问题契约 | `search_space_version`、candidate canonicalization、`objective_name/unit`、`constraints[]`、feasibility 与无可行点表示 | V1 仅单目标 minimize、约束 `g_i(x)<=0`；其他需新 contract；G-047 |
| Oracle | `oracle_adapter/version`、接受确认、attempt/idempotency、timeout scope、取消/重试/远端 reconciliation、真实成本来源与单位 | 不得把 P9c fake handle 当真实 worker；未知接受状态不得盲重发；G-045/G-048/G-049 |
| 角色 provider | `provider/model_snapshot`、prompt/allowed-fields、adapter、tokenizer、pricing、temperature、usage、凭据边界 | 真实 LLM/HTTP/密钥未授权也未验证；角色仍不得直接调用 oracle；G-051 |
| 噪声与 replicate | `noise_model`、异方差假设、`replicate_policy`、聚合、latent/observed 定义 | 不得把 P9a `none` 当真实默认；每个被接受的 replicate 单独计费；G-046 |
| Surrogate/acquisition | `surrogate/version`、校准/fit、failure/constraint/cost model、pool size/generator、baseline acquisition、tie-break | P9a nearest-observation/LCB 仅工程 Mock；EI/UCB/TS 尚未实现/验证；G-043/G-044/G-047/G-049 |
| 方法矩阵 | `single_agent_baseline`、`full_roles`、`no_roles`、`no_critic`、`no_integrator`、acquisition cells、memory choice | 同一 surrogate、初始观察、池、信息与预算；仅在 memory 已实现后加入 no-memory；G-050/G-051 |
| 并发 | `max_concurrency`、pending/reconciliation policy、完成事件顺序记录 | 真实并发与任意指令点恢复未实现；若启用，需另行协议/验证；G-048 |
| 指标/target | `primary_metric`、可靠 reference、`target`、失败/删失、cost-to-target、时间口径 | 无 reference 时仅可用 best-so-far 描述，不称 simple regret；G-050 |
| 随机性 | `root_seed_set`、`planned_repetitions`、派生规则、provider 非确定性说明 | 比较 cell 使用匹配 seeds；运行前冻结，不事后换 seed；G-050 |
| 统计 | `comparison_cells`、排除规则、paired bootstrap 输入、interval、多重比较/偏离方案 | 主分析与完整 run 表运行前冻结；G-050 |

## 4. 硬预算预注册表

以下值均为 `unset`；P9a/P9b 的五次 Mock oracle call、合成 token/成本和 Stage 5 的 USD
profile 均不得继承。每个比较 cell 必须有同一上限，实际消耗仍分开报告。

| 资源账本 | 每 run ceiling | 整个 campaign ceiling | 单位/作用域或准入规则 |
|---|---|---|---|
| 已接受 `oracle_calls` | `unset` | `unset` | accepted attempt 永久计数，不因失败/取消退款 |
| 成功/失败 evaluations 与候选提案 | `unset` | `unset` | 分列 `succeeded/failed/timed_out/cancelled`，不得折算为 calls |
| 角色 `llm_calls`、input/output tokens | `unset` | `unset` | 与 oracle calls 分账；usage 来源和模型 tokenizer/version 待定 |
| Oracle cost | `unset` | `unset` | `source/unit/expected upper bound/actual` 均为 `unset`；未知成本 fail closed |
| LLM/其他财务 cost | `unset` | `unset` | 币种、价格版本与换算规则为 `unset`；不同单位不得隐式相加 |
| Wall-clock 与 timeout | `unset` | `unset` | per-attempt/per-run/campaign scope 为 `unset`；不参与非时间 replay hash |
| 最大并发与 pending | `unset` | `unset` | 真实异步未实现；若开启需另行授权并验证对账 |

准入必须在消费前检查并保留 outstanding reservation；已接受的 attempt 即使结果无效、
超时或实际成本超预计，也必须如实结算并阻止后续超限发送。总预算不得由各 run 的
局部 ceiling 代替。`unset` 预算阻断真实运行。

## 5. 指标、失败与统计预注册

- `primary_metric=unset`。仅在 reference 可靠且最小化/可行性契约一致时，候选主指标可为
  `simple_regret(b)=best_feasible_observed(b)-reference_optimum`；否则仅描述 best-so-far，
  不以错误名称报告 regret。无可行成功观测的表示为 `unset`。
- `cumulative_regret` 的接受顺序、噪声下 latent/observed 选择和失败项处理为 `unset`；
  未冻结前不计算。`cost_to_target` 的 target、累计成本单位和未达标删失规则为 `unset`。
- 失败率分母为已接受 oracle calls；failed/timeout/cancelled、预算耗尽、无效数据、provider/
  oracle 错误和缺失结果单列。失败 Observation 的 objective/constraints 不得填 penalty。
- 每个可比较 cell 的现有 E4 统计门槛为至少 10 个完整匹配的独立 run seeds；实际 seed set、
  重复数、primary metric、排除和比较矩阵仍为 `unset`，须在 test/真实运行前冻结。
- 预注册后，对匹配完成 pairs 的方法差异使用 10,000 次 paired-bootstrap 的 95% percentile
  interval；报告 planned/completed/failed `n`、均值/中位数/样本标准差/min/max、失败率、
  原因与各维实际资源。interval 不是 p-value，不使用“显著”措辞。
- 失败 run 不删除、不重抽 seed、不插补 objective。completed-only objective 分析必须标为
  条件性并与全计划 run 失败表并列；偏离预注册须保留原记录及原因，不能覆盖主分析。
- 不跨 benchmark 汇总 raw objective、raw regret 或未经预注册归一化的 cost；结论范围不得
  超出精确的 benchmark/version/instance/split/provider/budget cell。

## 6. E2、E3 与 E4 的独立验收闸门

| 等级 | 必需工件 | 本模板当前状态 |
|---|---|---|
| E2：来源/许可 | 用户授权记录、source/release/license、使用范围和获取方式 | `unset`；不得下载 |
| E3：离线实现 | 本地 inventory/逐实例及总 checksum、split、目标/约束/evaluator/timeout、离线 Mock dry-run 与重放 | `unset`；不得把 P9 Mock 或 FSU MKP protocol-only 迁作 P10 benchmark |
| E4：真实结果 | 另行授权的真实 oracle/provider、运行前冻结的协议/预算/seed/统计、完整真实 run 与失败/重放工件 | `unset`；不得运行、报告性能或声称论文复现 |

E2/E3 是来源许可与离线适配证据，不是 E4 的真实效果证据。即使将来取得 E4，
也只能描述该精确协议下的观察结果；泛化、优越性或论文数值复现还需独立论证。

## 7. E4 工件清单与冻结点（仅供未来授权使用）

在首次 test/真实 run 前，冻结并记录：`protocol_id/version/hash`、用户授权与预算范围、
benchmark provenance/license/inventory/checksum/split、objective/constraint/reference、所有
method/surrogate/acquisition/pool/role/prompt/provider 版本、完整 seed set、预定 run/cell
矩阵、硬预算、primary/secondary metrics、失败/删失、统计脚本版本及偏离处理。

每条真实 run 应保存脱敏 manifest、Git SHA、环境/依赖、数据与配置摘要、派生 seed、
provider/model/tokenizer/pricing 版本、oracle request/attempt/accept/result/Observation 的
append-only 审计、pending/取消/失败事件、分离 ledger 的 ceiling 与 actual、原始安全
响应 hash、非时间 replay checksum 和无法确定性重放的说明。不得保存密钥、认证 header
或未脱敏上游正文；真实 wall-clock 作为观察量单列。

最终分析包应包含全部 planned/completed/failed run inventory、匹配 seed 表、统计输入
与可复核脚本、interval、失败/删失表、预算与成本账本、异常与偏离日志、结论适用范围。
缺文件、版本不符、预算不明或 oracle 接受状态无法对账时 fail closed，不升级到 E4。

## 8. 本模板的停止条件

任何来源/许可、问题/evaluator、真实 oracle/provider、凭据处理、单 run 与总预算、seed/
统计计划或结论范围仍为 `unset` 时，P10 停留在准备阶段。后续 E2/E3 适配、真实
transport、E4 运行分别需要新的明确任务授权；本文件、P9 提交和本轮文档更新均不构成授权。
