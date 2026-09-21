# ADR-0006：Stage 5 TSP-only 实验协议与离线 dry-run

- 状态：Accepted for Stage 5 P6 implementation
- 日期：2026-09-20
- 上游：ADR-0001 至 ADR-0005、`docs/paper_spec/parameter_registry.md`、`docs/gap_registry.md`
- 范围：TSP-50/TSP-100/TSP-200 数据清单、结果 schema、公平预算和 Mock/fake dry-run

## 背景

论文材料确认 TSP 是实验对象，并报告了小型 TSP 训练集、`N=10`、`T=3` 等若干设置；但当前本地
材料不足以唯一确认 TSP-50/100/200 的全部坐标生成规则、种子、测试实例数、完整 prompt、timeout
作用域、方法 multiplicity 及两个 400 上限的精确实验作用域。ADR-0001 已要求 calls、tokens、
candidates、valid evaluations、cost 和 wall time 分账，且禁止将 Mock 控制流结果表述为论文性能。

因此 P6 只建立可重放、完全离线的实验基础设施，不能下载论文数据、调用真实 provider 或报告模型
性能结论。

## 决策

### 1. 数据清单是版本化的生成/加载协议

`roco-tsp-dataset-manifest-v1` 只支持 TSP-50、TSP-100、TSP-200。每个
`roco-tsp-instance-v1` 记录：`instance_id`、规模、`train|test` split、派生 seed、
`python-random-mt19937-uniform-unit-square-v1` 坐标规则、完整坐标和 SHA-256 checksum。

实例 seed 是 `SHA-256(master_seed + schema + split + size + ordinal)` 的前 8 字节；坐标由
Python `random.Random(seed).random()` 顺序生成。checksum 对键排序、UTF-8、紧凑 JSON、禁止
NaN/Infinity 的完整实例载荷计算。manifest 还带总 checksum。加载时必须重新计算每个实例和
manifest checksum，任何 mismatch 都 fail closed。

除记录 checksum 外，系统还对只含规模/坐标/生成规则的 geometry checksum 去重。这样即使有人修改
`instance_id` 或 split，也不能让相同几何实例同时进入 train/test。默认 dry-run 每个
split/规模仅一例，是低成本工程 inventory，绝不是论文数据数量的声称。

### 2. white-box/black-box 是 prompt 可见性条件

`white_box` 表示 prompt 可以陈述已声明的 TSP 机制；`black_box` 表示 prompt 不得暴露坐标、距离
矩阵或 evaluator 内部状态。两者都不是昂贵 oracle，也不会改变 evaluator 或预算含义。

首次实施只有 seeded Mock；结果记录这两个条件及版本化语义，但 `mock_metadata_only=true`。Mock 不从
这些条件推导质量差异，故 dry-run 不比较、更不声称其有效性。既有 Stage 2/3/4 smoke 的 prompt 和
行为不改动。真实 prompt 渲染/模型实验必须另获授权，并先解决 G-035。

### 3. 每条结果记录完整账本与失败状态

`roco-tsp-experiment-result-v1` 的必需字段包括：run seed、split、实例 metadata/checksum、method、
provider/network 状态、prompt visibility、`llm_calls`、input/output tokens、cost、valid evaluations、
generated candidates、wall time、best score、status/failure 和硬预算/reached limits。每条还保存一个
忽略 wall time 的 replay checksum；同 seed/config/data 的非时间状态必须一致，wall time 只作为观察值。

`results.jsonl` 是严格输入，可写同字段的 `results.csv`。损坏 JSON、未知字段、重复 run ID、checksum
mismatch、NaN/Infinity、未知 method 和不完整预算 schema 都拒绝，不静默跳过。

### 4. 公平性是相同硬上限，不是相同偶然消耗

每个方法、规模、split、visibility 和 seed 都使用同一个 `ExperimentBudgets`：明确的 calls、tokens、
generated candidates、valid evaluations、cost 和 wall-time 六个 hard ceiling。先达到任一上限即停止新的
动作；实际消耗仍原样报告。EoH 和 RoCo 因控制流不同而可能消耗不同 calls，这不能被隐藏或误读为
“相同预算消耗”。默认工程 dry-run 设 24 calls/24 candidates/24 valid evaluations/120000 tokens/
1 USD/120 seconds；这些数值不是论文值。

比较接口当前接受 `eoh`、`roco` 和显式 opt-in 的 `memory_roco`。后者只有 `memory.enabled=true`
和独立 memory artifact root 时才可用，仍沿用 ADR-0004 的 Mock memory runtime；默认干跑只覆盖
EoH/RoCo，不改变三条既有 smoke 的 memory 边界。

### 5. 聚合只作描述性汇总

`roco-tsp-experiment-summary-v1` 按 method、seed、split、visibility、size 汇总 run/状态数、best-score
的均值/最小值、六类实际消耗总和与输入 replay checksums，并写 `summary.jsonl`/`summary.csv`。结果明确
标注为 descriptive only；不计算或暗示 p-value、置信区间或统计显著性。

## 后果与边界

该决策使 TSP 数据、预算和结果在不联网的 CI 中可复放，也能提前发现数据泄漏、账本缺字段和聚合输入
损坏。代价是默认 inventory 和预算只能验证接口，不能验证论文的数据分布、真实 tokenizer/价格、
provider 兼容性、prompt 质量或任意方法效果。

P6 明确不实现 MKP/OP/BPP/CVRP、GLS、EBBO、缓存、并行调度、下载数据、HTTP transport、真实 key 或
付费调用。任何真实实验仍需单独授权，并在 G-012/G-016/G-034/G-035 等缺口关闭后重新设置预算。
