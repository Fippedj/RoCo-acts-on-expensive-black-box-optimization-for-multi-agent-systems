# ADR-0007：Stage 5 多 COP 实验、统计与证据边界

- 状态：Accepted for Stage 5 P7a design; no implementation is authorized
- 日期：2026-09-21
- 上游：ADR-0001 至 ADR-0006、`docs/paper_spec/multicop_experiment_protocol.md`
- 范围：跨组合优化问题（COP）的实验记录、证据等级、统计预注册和 P7b 前置条件

## 背景

P6 只为合成确定性 TSP-50/100/200 建立了离线 Mock/fake dry-run。它的资料、实例、prompt、
timeout 和预算均不能被表述为论文原值或多问题性能证据。现有本地材料没有使 MKP、OP、BPP、CVRP
或 `GLS` 成为已支持 benchmark 的数据来源、许可证、实例 inventory、checksum、目标/约束 evaluator
或统计结果。

因此，在任何 COP 实现、下载、真实 provider 或实验之前，需要冻结“什么证据足以使一个候选问题进入
离线适配”、统一 run 记录和预注册统计规则，并禁止把不同问题的原始分数混合成方法优越性结论。

## 决策

### 1. 范围与候选状态

P7a 仅接受文档中的候选登记和实验协议。TSP 是唯一已有离线协议的 benchmark，且其 P6 inventory
仍是合成数据；MKP、OP、BPP、CVRP 和 `GLS` 均为**候选**，不是已支持、已下载、已实现或已复现的
问题。`GLS` 在本地材料中没有可冻结的全称、目标或 evaluator，不能进入 P7b，直至其语义和来源闭合。

P7a 不新增代码、运行时配置、数据、provider、测试或实验产物；不运行统计计算，也不产生性能数字。

### 2. 证据等级

每个候选 benchmark 必须在 manifest 中记录其最高证据等级，且不得跳级：

| 等级 | 含义 | 允许的表述 |
|---|---|---|
| E0 | 仅有候选名称或通用问题定义；没有经确认的来源/许可证 | “候选、未支持” |
| E1 | 有可定位的研究/来源线索，但未冻结可用数据 release、许可证或 evaluator | “有待核验的证据” |
| E2 | 已获明确授权的来源标识、release/version、许可证和实例获取方式；尚未验收本地 inventory | “来源与许可已登记，未适配” |
| E3 | 本地 inventory、逐实例/总 checksum、split、目标/约束/evaluator 和离线 dry-run 均已验证 | “已验证离线协议”，不得称论文复现或模型性能 |
| E4 | 在单独授权的真实实验与预注册下，完整记录 provider/version、预算、失败与重放工件 | “该精确协议下的观察结果”；不得自动外推为泛化或论文复现 |

任何性能、显著性、泛化、优越性或论文数值复现结论至少需要 E4 的真实实验工件以及与论文声明逐项
对应的独立证据；P7a 本身不会使任何新的候选 COP 达到 E3 或 E4。

### 3. 冻结的跨 COP 契约

`multicop_experiment_protocol.md` 是以下字段和术语的唯一规范：benchmark/version/source/license、
实例 inventory/checksum/split、方法/provider/prompt visibility、六类硬预算、结果/失败状态和
replay validation。`parameter_registry.md` 是这些参数名、默认规则和 P6 例外的唯一权威登记。

每个 run 必须能在不依赖 wall-clock 的条件下验证：数据与 split、固定配置、seed 派生、provider/prompt/
tokenizer/pricing 版本、预算 ledger、结果/失败状态及 replay checksum。wall time 是观察值，不是
可字节重放的状态。

### 4. 公平性、可见性和统计

方法比较的最低公平条件是同一 benchmark/version/instance/split/seed/visibility/provider-version 和
同一个六维 hard-budget profile。相同 ceiling 不是相同实际消耗；calls、tokens、generated candidates、
valid evaluations、cost 和 wall time 必须并列报告。black-box/white-box 是 prompt 信息可见性，不是
昂贵 oracle，且不得在同一比较单元中混用。

未来统计必须在运行前按 P7a 预注册：每个可比较单元至少 10 个匹配的独立 run seeds；报告全部计划、
完成和失败 run；报告描述统计；对匹配 seed 的方法差异以 10,000 次 paired bootstrap 的 95% percentile
interval 表达不确定性。P6 的三个 Mock seeds 不满足该规划下的统计样本量，只能维持 P6 的描述性
接口审计。失败 run 不得静默删除、重抽 seed 或插补 objective；必须单列失败率与原因，completed-only
分析只能标为条件性描述，不能替代全样本结论。

### 5. P7b 前置条件

在实施某一候选 COP 的离线数据适配/dry-run 前，必须逐问题具备并记录：

1. 用户明确授权的数据来源、使用范围和许可证；
2. 版本化 source/release 标识、实例 inventory、每实例及总 checksum；
3. 不重叠 train/validation/test split policy，及防止同一实例或等价实例泄漏的规则；
4. 目标方向、约束、可行性、候选表示、evaluator/timeout 和指标/reference 的版本化契约；
5. P7a 统一 schema、同一预算 profile、seed set、visibility 和 provider-version 记录；
6. 仅离线数据适配与 Mock/fake dry-run 的明确实施授权；真实 provider、网络、密钥、费用和性能实验
   仍需另一份明确授权。

缺少任一项时，候选仍停留在 E0/E1/E2，P7b 不得实现或下载数据。

## 后果

该决策把“候选问题清单”和“已支持 benchmark”分开，避免无许可证数据、未定义 evaluator 或不可比
分数被静默纳入实验。代价是 P7a 不给出 COP 性能结论、不提供可运行适配器，也不关闭数据或论文证据
缺口。P7b 的提交边界必须仅包含已获授权且已登记的离线数据适配、对应 dry-run、测试和 manifest；
不得顺带接入真实 provider、下载未授权数据或开始性能/显著性报告。
