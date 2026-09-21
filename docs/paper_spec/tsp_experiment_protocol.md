# Stage 5 TSP-only 实验协议

## 目的与证据边界

本规范是 Stage 5 P6 的离线工程协议，而不是论文数值复现。`paper.md` 的 `S009` 确认论文涉及 TSP、
报告 TSP 训练集示例为 5 个实例，并给出 `N=10`、`T=3` 与 400 calls/generation 的陈述；表格还出现
TSP-50/100/200。它没有在当前本地可执行材料中唯一给出所有 TSP 坐标、种子、test count、完整
white/black prompt、timeout 作用域或统一预算的可执行定义。因此这些值不得由本规范猜测。

相关缺口：G-012（calls/evaluations）、G-016（timeout）、G-021（候选 multiplicity）、G-034（数据
inventory）和 G-035（visibility prompt）。ADR-0006 固定下列工程口径。

## 1. 数据协议

支持的规模严格为 50、100、200。dataset config 给出 `master_seed`、各规模、train/test 数量和生成规则；
默认 dry-run 使用每个 split/规模一例。按以下稳定顺序创建：`train` 再 `test`，规模升序，再 ordinal 升序。

```text
instance_seed = first_8_bytes(SHA256(
  "<master_seed>:roco-tsp-dataset-manifest-v1:<split>:tsp-<nodes>:instance-<ordinal>"))
coordinates  = random.Random(instance_seed).random() pairs in [0, 1)
distance[i,j] = hypot(x_i-x_j, y_i-y_j)
```

`roco-tsp-instance-v1` 的 SHA-256 覆盖 schema、ID、规模、split、seed、rule 和坐标。JSON canonicalization
为 UTF-8、键排序、紧凑 separators、`allow_nan=false`。`roco-tsp-dataset-manifest-v1` 覆盖全部实例记录。
加载者逐项验 hash；manifest 还按 geometry checksum 阻止任何相同坐标在 train/test 或同一 inventory
重复出现。

数据清单保存于运行目录的 `dataset_manifest.json`；重放可经 `tsp-dry-run --dataset-manifest` 使用一个
已验证清单。它从不下载或宣称使用论文数据。

## 2. 条件、方法与公平预算

固定 dry-run seed 是 `[101, 202, 303]`，仅为工程 seed。方法接口为 `eoh`、`roco`，可选 `memory_roco`；
默认 config 只运行前两者。每个 `method × seed × split × instance × visibility` 得到一个 result。

`white_box` 与 `black_box` 是 prompt 信息可见性条件：前者可陈述公开的 TSP 机制，后者不允许坐标、矩阵
或 evaluator 内部状态。它们不是昂贵 oracle 条件。默认 Mock 对两者只记录 metadata，因而没有可以从
首次干跑推导的效果结论。

所有方法使用同一组硬上限：

| Counter | 默认 dry-run ceiling | 解释 |
|---|---:|---|
| LLM calls | 24 | provider 已记账调用 |
| input + output tokens | 120000 | Mock token 计数，仅作工程账本 |
| generated candidates | 24 | 解析出候选的数量 |
| valid evaluations | 24 | 有限 TSP score 的求值数 |
| cost | 1.0 USD | Mock 实际为 0，不代表真实价格 |
| wall time | 120 s | run 级工程上限，不代表论文 timeout |

上限相同而实际消耗可不同；默认一代 EoH 为 8 calls/8 valid evaluations，默认 T=2 的 RoCo 为
18 calls/13 valid evaluations。这是控制流审计，不是性能或论文预算比较。

## 3. Result schema

每行 `results.jsonl` 使用 `roco-tsp-experiment-result-v1`：

```text
run_id, replay_checksum, seed, split
instance { instance_id, nodes, split, seed, generator_rule, checksum }
method, provider { name=mock, model, network=unused }
prompt_visibility { schema_version, condition, semantics, mock_metadata_only }
llm_calls, input_tokens, output_tokens, cost, cost_currency
valid_evals, generated_candidates, wall_time, best_score
status = completed | budget_exhausted | failed
failure = null | { type, message }
budget { hard_limits, reached_limits, budget_reached }
```

`replay_checksum` 将 `wall_time` 规范为 null 后哈希；数据、候选、score 和离散账本必须稳定，但 wall-clock
本身不要求 byte-identical。相同内容以 CSV 镜像写入 `results.csv`。

## 4. 聚合与失败

读取 JSONL 时空行、坏 JSON、未知/缺失字段、重复 run ID、非有限值或 replay checksum 错误均 fail closed。
聚合键为 `(method, seed, split, prompt_visibility, nodes)`；每项只报告状态计数、best score 描述性均值/
最小值和实际预算总数。`summary.jsonl` 与 `summary.csv` 明示不含统计显著性分析。

验收必须覆盖：无效 instance、checksum mismatch、train/test geometry overlap、unknown method、NaN/Infinity
result、预算耗尽、损坏聚合输入，以及三个规模、两个 split、三个 seed、两 visibility 和 EoH/RoCo 的
Mock 执行。真实模型、网络、tokenizer/价格验证或任何论文性能声明不在本协议中。
