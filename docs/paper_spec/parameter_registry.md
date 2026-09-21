# RoCo 参数登记表

## 读取规则

- “明确披露”只表示当前精读材料可定位到论文陈述，不表示官方代码或完整实现已公开。
- `S009` 在 `paper.md` 中标为 p.5 与 p.12–13，但 `source_map.json` 只把该块挂到 p.5；涉及附录参数时保留这一证据粒度差异，待对原 PDF 复核。
- “第一版工程默认值”不是论文值时一律标记为工程决策；运行清单必须同时保存实际值。

| 参数名 | 论文给出的值 | 证据页码 / 块 ID | 是否明确披露 | 第一版工程默认值 | 说明 |
|---|---:|---|---|---:|---|
| `llm.model` | GPT-4o-mini | p.5、p.12–13 / `S009` | 是 | `gpt-4o-mini`；本地/CI 由 Mock 替代 | 服务端模型快照未披露；V1 优先 Mock 不等于论文模型 |
| `evolution.population_size` (`N`) | 10 | p.5、p.12–13 / `S009`；Top-N 见 p.3 / `S005` | 是 | 10 | Top-N 的 tie-break 未披露 |
| `evolution.collaboration_rounds` (`T`) | 3 | p.5、p.12–13 / `S009`；流程见 p.10 / `S008` | 是 | 3 | 初始 Critic 和最终 Integrator 不计入 `T` |
| `evolution.elite_sampling_power` (`k`) | 3.0 | p.10–13 / `S008`、`S009`（精读汇总） | 是，但 source map 粒度不足 | 3.0 | 排名权重按 `1/(i+1)^k`；边界和相邻伙伴细节仍需原 PDF 逐式复核 |
| `llm.temperatures.explorer` | 1.3 | p.12–13 / `S009`（精读汇总） | 是，但未单列原文块 | 1.3 | 运行时必须记录 |
| `llm.temperatures.exploiter` | 0.8 | p.12–13 / `S009`（精读汇总） | 是，但未单列原文块 | 0.8 | 运行时必须记录 |
| `llm.temperatures.critic` | 约 1.0 | p.12–13 / `S009`（精读汇总） | 部分明确 | 1.0 | 精读材料称“其余约 1.0”；精确 API 参数待 PDF/作者代码复核 |
| `llm.temperatures.integrator` | 约 1.0 | p.12–13 / `S009`（精读汇总） | 部分明确 | 1.0 | 同上 |
| 每代 LLM API 预算 | 400 calls / generation | p.5 / `S009` | 是 | `max_llm_calls: null`，实验必须显式设硬上限 | 不能自动等同于评估次数；`null` 防止伪装成已解决口径 |
| 最大评估预算 | maximum 400 evaluations | Appendix D（`START_HERE.md` 与路线图的冲突记录；当前 source map 无独立块） | 有陈述但证据锚点不足 | `max_valid_evals: 400` | 与“每代 400 calls”可能是不同实验口径；必须分别记账并在 manifest 声明作用域 |
| `G`（总代数） | 未披露/无法由当前材料唯一确定 | p.10 / `S008` 仅描述代循环；`S011` 指出成本口径不完整 | 否 | 不写死；由显式预算终止 | smoke 配置中的 `G=2` 只能是工程测试值 |
| 精英对数量/每代协作次数 | 未披露到可执行粒度 | p.10 / `S008` | 否 | 待 Stage 2 配置化 | 直接影响调用数和候选数，不能从 400 反推 |
| 每个精英的记忆变异数 | 三种角色视角 | p.10 / `S008` | 角色数明确，精英集合大小不明确 | 每个精英 3 个（Explorer、Exploiter、Integrator） | ADR-0001 固化 V1 |
| `memory.recent_events` (`K`) | 未披露 | p.4 / `S007`；缺失性见 p.10–16 / `S011` | 否 | 5 | ADR-0001 工程决策 |
| `memory.backend` | 未披露 | p.10–16 / `S011` | 否 | JSONL | ADR-0001 工程决策 |
| 每角色输入/输出 token 上限 | 未披露 | p.10–16 / `S011` | 否 | 暂不在 paper preset 伪设数值；Stage 2 必须显式配置 | 路线图中的 6k/1.2k、4k/500、6k/250 是建议，不是论文值 |
| 无效代码修复重试 | 未披露 | p.10–16 / `S011` | 否 | 最多 2 次（待后续 ADR/配置） | 每次修复仍计 LLM call；本阶段不实现 |
| `run.seed` | 未披露 | p.10–16 / `S011` | 否 | 2025 | 纯工程默认值；必须记录所有随机源 |
| 普通训练超时 | 当前精读材料未给出可独立核验值 | `S009` 涵盖 p.12–13 实验设置，但无逐项原文；`S011` | 否/证据不足 | 60 s | 现有配置值仅作工程占位，需在 Stage 2 evaluator 协议前复核 PDF |
| CVRP 训练超时 | 当前精读材料未给出可独立核验值 | 同上 | 否/证据不足 | 120 s | 现有配置值仅作工程占位，不能称论文默认值 |
| TSP 规模 | TSP-50、TSP-100、TSP-200 出现在结果表/GLS 比较 | p.6–7 / `T001`–`T004` | 是（规模），否（完整 instances） | 三个规模均由版本化 deterministic generator 提供 | 坐标分布、种子、test count 与 corpus checksum 未由当前材料确认；见 G-034 |
| TSP 训练实例数 | 举例为 5 个 TSP instances | p.5、p.12–13 / `S009` | 是（训练数陈述），否（具体实例） | P6 default 每 split/size 1，仅为快速 dry-run | 工程 inventory 不得替代论文训练集或暗示相同数据分布 |
| P6 dry-run seeds / split count | 未披露到可执行粒度 | `S011`；G-018/G-034 | 否 | `[101, 202, 303]`，每规模 train/test 各 1 | 固定三 seed 是接口验收条件，不是论文的独立运行设定 |
| P6 all-method hard ceilings | 未披露统一可执行规则 | G-012/G-021 | 否 | 24 calls、120000 Mock tokens、24 candidates、24 valid evals、1 USD、120 s | ADR-0006 工程公平定义为同上限，实际消耗另报；不是论文预算 |
| white/black visibility prompt | 两种 setting 存在，但完整 prompt 未可执行披露 | p.1–2 / `S003`；`S011` | 部分明确 | `roco-prompt-visibility-v1` metadata-only Mock condition | 不是昂贵 oracle；真实 prompt 内容/效果仍为 G-035 |
| EoH E1/E2/M1/M2 每算子候选数 | 未披露到当前 source blocks | p.3 / `S005` | 否 | 待 Stage 2 配置化 | 必须纳入 candidate/call 数量推演 |
| Top-N tie-break | 未披露 | p.3 / `S005` | 否 | 稳定排序 + 明示的候选 ID tie-break（待实现 ADR） | 不得依赖并行完成顺序 |

## 400 calls 与 400 evaluations 的处理

两句话不能互相替代：一次调用可能不产生候选、产生无效代码或产生一个待评估候选；一次候选评估也可能因修复、缓存、重复或超时而与调用数不一一对应。第一版因此分别记录 `llm_calls`、`tokens`、`generated_candidates`、`valid_evals`、`cost`、`wall_time`，每个实验显式指定至少一个硬停止预算。复现实验报告必须同时展示各账本值，不能把“达到 400 calls”写成“达到 400 evaluations”。

## 训练超时处理

`configs/paper_defaults.yaml` 现有的 60/120 秒值继续保留，以免无证据改变行为，但注释应明确它们是待核验的工程占位值。Stage 2 在实现 evaluator 前需要回看原 PDF 的 Appendix D/实验设置，确定超时作用于单实例、单候选、单求解器运行还是整批训练；在此之前不得用 `paper_*` 命名或报告成作者原设定。
