# RoCo 单代可执行规格

## 范围与证据约定

本文只把论文描述转换为可实现的状态机，不补写未披露的调用次数、prompt、重试或并行策略。证据引用采用 `docs/paper/paper.md` 的页码与块 ID；`S008` 是 p.10 算法伪代码的摘要，`S005`、`S006`、`S007` 分别约束 EoH 合并、角色职责与长期反思。

以下记号中，`P_g` 是第 `g` 代开始时已评估的种群，`|P_g| = N`；候选至少携带唯一 ID、父代 ID、生成算子/角色、代数、可执行内容、验证状态和目标值。`better(a, b)` 必须由任务的优化方向决定，不能默认全部为最小化。

## 状态与转换

| 状态 | 必需输入 | 动作 | 必需输出 | 下一状态 | 依据 |
|---|---|---|---|---|---|
| `G0_VALIDATE` | `P_g`、配置、剩余预算 | 验证 `N >= 2`、`T >= 1`、种群已评估且至少一个硬终止预算非空；按目标值稳定排序 | `ranked(P_g)` | `G1_EOH` | Top-N：p.3 `S005`；参数：p.5、p.12–13 `S009`。前置校验是工程要求（ADR-0001） |
| `G1_EOH` | `ranked(P_g)` | 运行 EoH 的 E1、E2、M1、M2，保留每个有效/无效输出的来源；此分支可与 RoCo 分支独立调度，但合并前必须完成 | `C_eoh` | `G2_SAMPLE_PAIR` | p.3 `S005` |
| `G2_SAMPLE_PAIR` | `ranked(P_g)`、随机源 | 以精英偏置权重采样基座，并按论文伪代码选择相邻排名伙伴；记录采样概率、排名、seed 与结果 | 精英对 `(h_a, h_b)` | `G3_INITIAL_CRITIC` | p.10 `S008`；`k=3.0` 的参数证据见 p.12–13 `S009` 汇总 |
| `G3_INITIAL_CRITIC` | `(h_a, h_b)` 及其目标值 | Critic 比较两者，产生分别可供 Explorer/Exploiter 使用的初始反馈；不得仅凭文本声称更优 | `f^E_0`、`f^X_0`、初始短期反思事件 | `G4_INIT_BRANCHES` | p.4 `S006`；p.10 `S008` |
| `G4_INIT_BRANCHES` | 精英对、初始反馈 | 初始化 Explorer 与 Exploiter 的当前候选、反馈历史和轮次计数 `t=1` | `E_0`、`X_0`、`t=1` | `G5_ROUND_PROPOSE` | p.10 `S008` |
| `G5_ROUND_PROPOSE` | `E_{t-1}`、`X_{t-1}`、对应 Critic 反馈 | Explorer 生成强调新颖性/多样性的候选；Exploiter 生成保守精炼候选。两路逻辑独立，执行次序不得造成隐式信息泄露 | 未评估的 `E_t`、`X_t` | `G6_ROUND_EVALUATE` | p.4 `S006`；p.10 `S008` |
| `G6_ROUND_EVALUATE` | `E_t`、`X_t` | 验证并评估两路候选；分别登记 generated candidate 与 valid evaluation，失败也保留审计事件 | 带验证状态和分数的 `E_t`、`X_t` | `G7_ROUND_CRITIC` | p.4 `S006`、`S007`；分账规则见 ADR-0001 |
| `G7_ROUND_CRITIC` | 前后候选及其目标值 | Critic 分别比较前后版本，生成针对性反馈，并记录前值、后值、方向正确的 `delta_g`、是否改进 | `f^E_t`、`f^X_t`、两路短期反思事件 | `G8_ROUND_GATE` | p.4 `S006`、`S007` |
| `G8_ROUND_GATE` | `t`、`T`、分支状态 | 若 `t < T`，令 `t := t + 1`；否则结束精炼 | 更新后的轮次状态 | `G5_ROUND_PROPOSE` 或 `G9_FINAL_INTEGRATOR` | p.1–2 `S003`；p.10 `S008` |
| `G9_FINAL_INTEGRATOR` | 最终 Explorer/Exploiter 候选、分数及反馈 | Integrator 依据两路目标值与提案生成融合候选；验证并评估。融合是新候选，不得把语言判断当作分数 | `C_roco`（含最终融合候选及可追溯的协作候选） | `G10_LTREFLECT` | p.4 `S006`；p.10 `S008` |
| `G10_LTREFLECT` | 全部短期反思、前后目标值、历史角色记忆 | 将反思压缩为角色特定的长期反思；Explorer 与 Exploiter 的长期反思另行合并，供集成视角使用；追加本代记忆事件 | 更新后的角色记忆与集成记忆 | `G11_MEMORY_MUTATION` | p.4 `S007` |
| `G11_MEMORY_MUTATION` | 每个精英基座、三类角色记忆 | 对每个精英分别从 Explorer、Exploiter、Integrator 三种视角各生成一个变异；逐个验证、评估并记账 | `C_memory` | `G12_MERGE` | p.10 `S008`；三变异 V1 决策见 ADR-0001 |
| `G12_MERGE` | `P_g`、`C_eoh`、`C_roco`、`C_memory` | 合并候选；按候选 ID/内容哈希执行可审计去重，不得静默丢弃失败记录 | 候选池 `U_g` | `G13_SELECT` | p.3 `S005`；p.10 `S008` |
| `G13_SELECT` | `U_g` 中的有效已评估候选 | 按任务目标方向确定性排序；同分 tie-break 必须在配置/manifest 中声明；保留前 `N` 个 | `P_{g+1}` | `G14_COMMIT` | p.3 `S005` |
| `G14_COMMIT` | `P_{g+1}`、预算账本、记忆事件 | 原子化保存代际结果、谱系、预算快照和记忆位置；检查任一硬预算是否耗尽 | 已提交的一代；继续或停止 | 下一代 `G0_VALIDATE` 或终止 | 审计与终止语义：ADR-0001（工程设计） |

## 控制流伪代码

```text
function generation(P_g, config, ledger, memory, rng):
    require len(P_g) == N and N >= 2 and T >= 1
    require config defines at least one hard stopping budget
    ranked = stable_objective_sort(P_g)

    C_eoh = run_and_evaluate(E1, E2, M1, M2, ranked, ledger)
    h_a, h_b = sample_elite_pair(ranked, power=k, rng=rng)

    feedback_E, feedback_X = critic_initial(h_a, h_b, ledger)
    E, X = initialize_branches(h_a, h_b)
    short_reflections = []

    for t in 1..T:
        E_new = explorer(E, feedback_E, ledger)
        X_new = exploiter(X, feedback_X, ledger)
        evaluate_if_valid(E_new, ledger)
        evaluate_if_valid(X_new, ledger)
        feedback_E, event_E = critic_compare(E, E_new, ledger)
        feedback_X, event_X = critic_compare(X, X_new, ledger)
        short_reflections += [event_E, event_X]
        E, X = E_new, X_new

    fused = integrator(E, X, feedback_E, feedback_X, ledger)
    evaluate_if_valid(fused, ledger)
    role_memory = ltreflect(short_reflections, objective_values, memory, ledger)

    C_memory = []
    for elite in ranked_elites(P_g):
        for role in [explorer, exploiter, integrator]:
            child = memory_guided_mutation(elite, role_memory[role], ledger)
            evaluate_if_valid(child, ledger)
            C_memory.append(child)

    U_g = auditable_merge(P_g, C_eoh, collaboration_trace, fused, C_memory)
    P_next = deterministic_top_n(valid_evaluated(U_g), N, objective_direction)
    commit(P_next, ledger, role_memory, lineage)
    return P_next
```

`ranked_elites(P_g)` 的数量/定义、E1/E2/M1/M2 各自产生几个候选，以及无效候选是否补位，现有材料没有可执行级定义；实现前必须由配置显式给出，并标记为工程设计，不能由这段伪代码暗示固定值。

## 不变量与验收检查

- 每个 LLM 返回都增加一次 `llm_calls`，无论是否解析成功；每个解析出的新方案增加 `generated_candidates`；只有完成目标函数求值的候选增加 `valid_evals`。
- `delta_g` 必须采用统一的“正值代表改进”约定，并保留原始前后目标值，兼容最大化与最小化任务。
- 任何进入 Top-N 的个体都必须有有效评估、完整父代/算子谱系和预算事件。
- 轮次必须恰为 `T`；初始 Critic 不计作精炼轮，最终 Integrator 不计作额外轮。
- EoH、RoCo 与 memory mutation 的候选不得在评估前仅凭 LLM 自评排序。
- 硬预算在每次可能消费预算的动作前检查；达到任一配置上限时停止产生新工作，并保存可恢复状态。

## 仍需 Stage 2/3 定义的接口

状态机依赖但不在 Stage 1 实现：`Candidate`、`EvaluationResult`、`BudgetLedger`、`RunManifest`、确定性随机源、验证/评估接口、Mock LLM provider。角色 prompt、真实 LLM、EoH 算子和 TSP evaluator 均不属于本阶段交付。
