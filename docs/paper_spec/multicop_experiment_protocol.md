# Stage 5 多 COP 实验与统计协议（P7a 设计）

## 0. 状态、范围与禁止结论

本文件是 P7a 的冻结设计，配合 ADR-0007 使用；它不是 COP 实现、数据清单、实验配置或结果报告。
P7a 已设计但尚未提交。P6 的 `a94ce0c`/`7302ddd` 仅在本地，未设置 upstream；任何后续会话必须用
实时 Git 查询确认该状态。

唯一已有离线协议的是 P6 合成确定性 TSP-50/100/200。它不提供论文原始数据、真实模型实验或统计
证据。MKP、OP、BPP、CVRP 和 `GLS` 在此只作候选登记，均未被实现、下载、支持或复现。

在没有 E4 真实实验、完整 provenance 和预注册工件前，禁止写出性能、显著性、泛化、优越性、
跨问题总排名或论文复现结论。即使未来取得 E4，结论也只可限于预注册的精确 benchmark/version/
instance/split/provider/budget 条件。

## 1. 候选 COP 登记

下表的“暂定”是为声明未来 evaluator 必须冻结的字段，不是关于论文所用变体、数据或结果的陈述。
`E0`–`E4` 的含义由 ADR-0007 定义。

| 候选问题 | 暂定目标方向与约束字段 | 本地实例来源/许可证状态 | 规模与指标状态 | 已验证证据 | 未知项与进入 P7b 前的阻断 |
|---|---|---|---|---|---|
| TSP | minimize closed-tour length；permutation、一次访问、闭环为 P6 合成协议的约束 | P6 synthetic generator，非论文数据；没有论文 corpus 来源或许可证 | P6 仅为 50/100/200；记录 finite tour length，若用 gap 必须先冻结 reference | E3 仅适用于 P6 synthetic/Mock protocol | 论文实例、许可证、完整 inventory/checksum、test 数量、timeout、prompt 和真实实验均未知（G-012/G-016/G-021/G-034–G-036） |
| MKP | 暂定 maximize value；容量/多背包约束、物品表示和可行性尚待版本化 | 未登记来源、release 或许可证 | 未冻结规模、metrics/reference 或 evaluator | E0 | G-037–G-040：来源/许可证、instances/checksum/split、目标/约束/evaluation 均未闭合 |
| OP | 暂定 maximize collected reward；路由预算、访问和奖励规则尚待版本化 | 未登记来源、release 或许可证 | 未冻结规模、metrics/reference 或 evaluator | E0 | 同上；不得把任意 Orienteering 变体当作论文/项目 benchmark |
| BPP | 暂定 minimize bins；容量、item dimensions、在线/离线和可行性尚待版本化 | 未登记来源、release 或许可证 | 未冻结规模、metrics/reference 或 evaluator | E0 | 同上；目标/约束变体会改变比较语义 |
| CVRP | 暂定 minimize route cost；需求、车辆容量、depot、车辆数和可行性尚待版本化 | 未登记来源、release 或许可证 | 未冻结规模、metrics/reference 或 evaluator | E0 | 同上；现有 120 s 只是旧工程占位，非 CVRP 论文 timeout 证据（G-016） |
| GLS | 缩写的全称、目标方向和约束均未知，不能推断 | 未登记来源或许可证 | 未冻结 | E0 | 必须先确认术语、问题定义、来源、license、instances、checksum 与 evaluator；在此之前不进入 P7b |

候选只有在 ADR-0007 的 P7b 前置条件都满足后才可被称为“已验证离线协议”（E3）；这不等同于
“已支持真实实验”或“已复现”。

## 2. 可比性边界

### 可以直接比较

仅可在完全相同的 benchmark、version、instance checksum、split、objective/evaluator contract、
seed、visibility、provider-version、prompt version 和 hard-budget profile 内，比较不同方法的：

- 已预注册的同向 objective 或其预注册的 paired difference；
- 可行/无效/失败状态及其原因；
- 六类实际预算消耗和是否达到 ceiling；
- 重放校验是否通过。

同一方法在不同 COP 上的 schema 覆盖率、manifest 完整性和失败分类可以审计，但不能用作算法性能
排名。TSP P6 的 3-seed Mock 结果只可验证该 schema/ledger/replay 接口。

### 不可以直接比较

不得跨 COP 对原始 objective、best score、百分比 gap、可行率、运行时间、token/cost 或“胜场”求均值、
排名或宣称方法优越。目标方向、约束、实例分布、evaluator、reference、硬件/timeout 和 provider 都可能
不同。没有同一已验证 reference 的 gap 不能计算；没有匹配 seeds 的结果不能做 paired 比较；没有真实
实验和充分证据时不得写显著性、泛化或论文数值复现。

## 3. 统一 run record

每个 run 应采用后续版本化 schema（建议名 `roco-multicop-experiment-result-v1`），至少记录：

```text
run_id, schema_version, replay_checksum
benchmark { id, version, evidence_level, source_id, release, license_id }
dataset { inventory_checksum, instance_id, instance_checksum, split, split_policy_version }
randomness { root_seed, derived_run_seed, provider_seed_or_nondeterminism_note }
method { id, version, implementation_git_sha }
provider { name, network_state, model, adapter_contract, tokenizer_counter, pricing_version }
prompt_visibility { contract_version, condition, allowed_fields_hash, prompt_version_or_hash }
budget { profile_id, hard_limits, actual { llm_calls, input_tokens, output_tokens,
  generated_candidates, valid_evals, cost, cost_currency, wall_time }, reached_limits }
evaluation { objective_direction, evaluator_contract, timeout_scope, result, feasibility,
  metric_name, reference_version_or_null }
status = completed | budget_exhausted | invalid | failed
failure = null | { phase, type, safe_message }
replay { dataset_verified, split_verified, result_verified, non_time_state_verified }
```

`replay_checksum` 对 canonical JSON 计算，`wall_time`、日期和其他非确定性观察值规范为 `null`。
hash 通过不证明模型输出可重现；真实 provider 必须记录不能确定性的原因和版本。缺失、未知、非有限、
不一致的 checksum/split/contract 或不完整的 budget/failure 字段一律 fail closed。

## 4. 公平预算、数据隔离、visibility、随机性与 provider

### 4.1 预算

`budget.profile_id` 必须引用同一六维 hard ceiling：LLM calls、input/output tokens、generated
candidates、valid evaluations、cost 和 wall time。所有比较方法在一个可比较单元中使用完全相同的
profile；首先触及任何 ceiling 后不得启动新的消费动作。实际用量不必相同且必须原样报告。

P6 的 `24/120000/24/24/1 USD/120 s` 仅是 TSP Mock dry-run profile，不能自动成为其他 COP 或
真实实验默认值。P7b 必须在数据授权和 evaluator scope 已知后预注册一个新的 profile，并说明其
每一维的作用域。

### 4.2 数据与 split

训练、validation（若使用）和 test 必须由版本化 split policy 指定且互不重叠；任一语义等价/同一
geometry/重复 instance checksum 都不得跨 split。只允许用 train/validation 做 prompt、方法或预算
选择；test 必须在设计冻结后一次性执行，且 run record 显式标出 split。不能确认 provenance 或
checksum 的实例不得进入任何 split。

### 4.3 prompt visibility

visibility 是信息集契约，不是昂贵 oracle。每个 condition 必须记录允许字段清单 hash、禁止字段、
prompt contract/version 或 hash。black-box 不可因 convenience 泄露内部状态；white-box 不可因 method
不同而额外泄露字段。一个比较单元只能包含同一 visibility condition；不同 condition 是单独的实验
因素，不能混入同一主结论。

### 4.4 随机性与 provider 版本

预注册 root seed set，按 benchmark/version/instance checksum/split/condition/method 派生 run seed；
所有方法使用匹配的 seed set。provider 记录 name、network 状态、model snapshot、adapter contract、
tokenizer counter、pricing、prompt 和必要的 concurrency/temperature settings。Mock 可承诺非时间状态
重放；真实 provider 不得声称完全确定性，必须保存安全的 request/response hashes、usage 和版本元数据。

## 5. 预注册统计计划（供 E4 授权实验使用）

这是一份分析规则，不是已有结果。每个可比较 cell 的预注册最低规模为 10 个匹配的独立 run seeds；
实际 `R`、完整 seed set、primary metric、objective direction、reference、budget profile 和 exclusions
必须在任何 test/真实 run 前固定。少于 10 个完整匹配 runs（包括 P6 的 3 个 Mock seeds）只报告描述性
审计，不报告 interval、显著性或方法优越。

对每个 cell 报告 planned/completed/failed `n`、mean、median、sample standard deviation、min/max、
失败率、每种失败原因和六类实际预算。方法差异只在同一 cell 的匹配 seeds 上形成；以 10,000 次
paired bootstrap 的 95% percentile interval 报告差异不确定性。该 interval 不是 p-value，不使用
“statistically significant”措辞，也不得跨 COP 聚合。

预算耗尽、无效输出、evaluator/provider 错误和缺失结果都是 run outcome：不删除、不以更换 seed
重跑掩盖、不插补 objective。主表报告全体计划 run 的状态；只有完整匹配的 completed pairs 可进入
conditional completed-only objective 描述，并必须与失败率并列且标注条件性。任何临时重跑、异常排除、
指标转换或分析变更必须保留原记录并另列为偏离预注册，不能覆盖主分析。

## 6. P7b 实施闸门

P7b 只能在用户明确授权数据来源与使用后，为已登记的单个 COP 实现离线数据适配和 Mock/fake dry-run。
每个拟实施问题需先在 G-037–G-041 中附上关闭证据：source/release/license、实例 inventory/checksum/
split、objective/constraint/evaluator/timeout/metrics、预算/seed/visibility/provider contract，以及测试计划。
P7b 不授权下载、真实网络/provider、密钥、付费请求、性能/显著性报告或其他 COP 的顺带实现。
