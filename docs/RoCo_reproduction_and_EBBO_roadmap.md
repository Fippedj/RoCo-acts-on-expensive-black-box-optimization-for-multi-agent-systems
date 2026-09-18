# RoCo 复现与多智能体昂贵黑盒优化迁移路线

> 目标论文：Jiawei Xu, Fengfeng Wei, Weineng Chen, *RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design*, arXiv:2512.03762（2025）
> 目标仓库：<https://github.com/Fippedj/RoCo-acts-on-expensive-black-box-optimization-for-multi-agent-systems>
> 开发约束：所有本地开发、测试和实验均在 Anaconda/Miniconda 环境中完成。

## 0. 总体判断与复现边界

结论：**可做方法级复现，也适合继续迁移，但目前无法承诺论文表格的逐项数值复刻。** 原因是论文已经给出角色、协作顺序、EoH 接入方式、关键实验参数和提示词主体，足以重建算法；但没有完整披露长期记忆的数据结构、检索与截断、全部调用预算口径、无效代码重试策略、随机种子及模型快照等实现细节。

建议把“复现成功”分为三级：

1. **L1 工程复现**：四角色、T 轮协作、反思、记忆变异、EoH 合并与 Top-N 选择全部可运行，预算严格可审计。
2. **L2 行为复现**：完整 RoCo 相比去掉 Critic/Integrator/长期记忆的版本呈现论文相同或相近的消融趋势。
3. **L3 数值复现**：在同类模型与等预算下，TSP 等任务的均值和方差进入论文结果的预设容差区间。由于 GPT-4o-mini 的服务端版本不可冻结，L3 应被视为增强目标，不应作为前两级的否决条件。

尤其要区分两个“黑盒”：论文中的 black-box 是**不给 LLM 显式问题语义，只提供抽象边属性**；拟迁移的昂贵黑盒优化是**目标函数值只能通过代价高昂的 oracle 调用获得**。第 6 阶段不是简单换数据集，而是优化对象和预算机制的实质重构。

## 1. 已知、未知与第一版决策

### 1.1 论文已明确的内容

| 项目 | 论文依据 | 复现处理 |
|---|---|---|
| 四角色 | Explorer、Exploiter、Critic、Integrator 的职责与策略已定义 | 按角色实现独立 prompt、温度和结构化输出 |
| 协作顺序 | 精英对 → 初始 Critic → T 轮双路精炼 → Integrator 融合 | 固化为状态机，不依赖自由聊天 |
| EoH 接入 | E1/E2 探索、M1/M2 修改、候选合并、Top-N | 保留 EoH 适配器和统一 Candidate 数据模型 |
| 短期/长期反思 | Critic 每轮反馈；LTReflect 结合前后目标值及 Δg | 反馈与数值变化绑定，禁止只存自然语言 |
| 记忆引导变异 | 每个精英按三种角色视角生成变异 | V1 每个精英固定三次变异调用 |
| 主要参数 | GPT-4o-mini；N=10；T=3；精英采样指数 k=3.0 | 作为 `paper_defaults.yaml` 默认值 |
| 角色温度 | Explorer 1.3、Exploiter 0.8、其余约 1.0 | 可覆盖配置并写入 run manifest |
| 任务与数据规模 | TSP/MKP/OP/BPP/CVRP；训练/测试规模、超时规则 | 先 TSP，再按难度逐项接入 |

论文证据锚点见配套精读稿：`p.1–2 S001–S003`、`p.2–3 S004–S005`、`p.4 S006–S007`、`p.10 S008`、`p.5 与 p.12–13 S009`。

### 1.2 论文未完全定义的内容及工程约定

| 缺口 | V1 最简实现 | 后续优化方向 |
|---|---|---|
| LTReflect 存储结构 | 每个角色一条 `RoleMemorySummary`；原始事件追加到 JSONL；字段包括输入候选、反馈、前后分数、Δg、成功/失败、代数 | SQLite/向量索引；质量加权检索；任务级、问题级与全局分层记忆 |
| LTReflect 检索 | 最近 `K=5` 条有效事件 + 当前累计摘要；超过 token 上限先丢最旧原文，保留数值统计 | 基于相似度、贡献度、失败模式和多样性的混合检索 |
| memory-guided mutation prompt | 统一模板：角色视角 + 当前精英 + 长期总结 + 最近成功/失败证据 + 输出契约；每个精英三种角色变异 | 按角色在线学习模板；基于历史增益自适应选择变异类型 |
| agent 通信 token 预算 | 强制结构化短消息；Critic/LTReflect 输出较短，代码代理较长；每次调用记录 input/output token 与费用 | 基于“单位 token 预期改进”动态停止、压缩和路由到不同模型 |
| G 与 400 的口径 | 不猜固定 G；同时维护 `llm_calls`、`generated_candidates`、`valid_evals`、`tokens` 五本账，实验按配置中的首个硬上限停止 | 通过公开实现或作者回复确定论文口径后补齐严格 preset |
| 无效代码 | AST/签名静态检查 → 沙箱小样例 → 最多 2 次修复 → 仍失败记为无效且消耗生成预算 | 基于错误类型的修复代理和可靠性模型 |
| 上下文截断 | 优先保留任务契约、当前精英、最佳/最差证据和 Δg，删除重复对话 | 语义压缩、分层摘要、信息价值估计 |
| 并行与随机性 | V1 串行状态机，所有随机源显式 seed | 异步批评估、并行 oracle、pending-point 建模 |

建议的 V1 token 上限是**工程假设，不是论文参数**：Explorer/Exploiter/Integrator 输入 6k、输出 1.2k；Critic 输入 4k、输出 500；LTReflect 输入 6k、输出 250。实际使用时按模型上下文调整，但任何改动必须进入实验清单。

## 2. 推荐仓库架构

采用“轻量独立核心 + 外部基线适配器”，不深度 fork 某个平台。当前 LLM4AD_Next 已提供 EoH/ReEvo 的工作 orchestrator，可作为接口与结果校验参考；RoCo 的核心仍放在自己的包内，避免第 6 阶段被 AHD 专用抽象锁死。

```text
.
├─ environment.yml
├─ environment-baselines.yml          # 仅在旧 ReEvo 依赖冲突时使用
├─ pyproject.toml
├─ .env.example
├─ configs/
│  ├─ paper_defaults.yaml
│  ├─ smoke/tsp_mock.yaml
│  ├─ reproduction/{tsp,mkp,op,bpp,cvrp}/
│  └─ ebbo/{synthetic,botorch,real_world}/
├─ src/roco_ebbo/
│  ├─ core/                            # candidate、population、budget、事件
│  ├─ llm/                             # provider、重试、token/费用记账
│  ├─ agents/                          # 四角色
│  ├─ collaboration/                   # T 轮状态机
│  ├─ memory/                          # 短期、长期、跨代记忆
│  ├─ evolution/                       # EoH/Top-N/采样/变异
│  ├─ evaluation/                      # 沙箱、超时、缓存
│  ├─ benchmarks/                      # 五个 COP
│  ├─ baselines/                       # LLM4AD/EoH/ReEvo adapter
│  └─ ebbo/                            # oracle、surrogate、acquisition、scheduler
├─ prompts/                            # 版本化模板与输出 schema
├─ tests/{unit,integration,regression}/
├─ scripts/{smoke,reproduce,aggregate}/
├─ docs/{paper_spec,gap_registry,adrs,protocols}/
├─ results/                            # 仅提交小型汇总、manifest、图表
└─ .github/workflows/ci.yml
```

主开发环境建议使用 **Linux/WSL2 + Conda + Python 3.11**，优先保证科学计算、进程超时和旧基线兼容性。当前 LLM4AD_Next 要求 Python 3.12+，因此把它放入可选的 `llm4ad-next` Conda 环境，通过 adapter/CLI 对接，而不让它决定 RoCo 核心环境。如 ReEvo 原仓库仍有旧依赖冲突，再单独建立 `roco-baselines` 环境。论文没有披露操作系统、Python 版本或硬件，因此以上是可移植工程决策，不是对作者环境的声称。

```powershell
conda env create -f environment.yml
conda activate roco-ebbo
python -m pip install -e .
pytest -q
python -m roco_ebbo.cli smoke --config configs/smoke/tsp_mock.yaml
```

CI 使用 `MockLLMProvider`，不调用收费 API；API key 只通过环境变量注入，`.env`、原始对话和可能包含密钥的运行目录均不得提交。

## 阶段 1：论文精读与缺失模块确认（3–5 天）

### 具体任务

1. 把算法 1、全部角色 prompt、表 5/6 参数拆成可执行 specification。
2. 建立“原文明确 / 合理推断 / 自行设计”三列证据矩阵，所有自行设计项分配 ADR 编号。
3. 明确预算术语：LLM call、候选生成、成功编译、有效评估、oracle evaluation、token、美元费用。
4. 固化 V1 参数：`N=10`、`T=3`、`k=3.0`；G 不写死，使用预算终止。另设 smoke：`N=4,T=1,G=2`。
5. 逐条校对附录 prompt；将 Critic 中疑似 “better/worse” 复制错误登记为歧义，不静默修正。
6. 写预注册式复现实验协议：数据、seed、模型、温度、超时、统计方法、失败处理。

### 关键交付物

- `docs/paper_spec/algorithm.md`：逐步伪代码与状态转换。
- `docs/paper_spec/parameter_registry.csv`：参数、值、出处、置信等级。
- `docs/gap_registry.md`：缺失项、V1 决策、替代方案、风险。
- `docs/adrs/0001-*.md`：预算口径、记忆结构、基线选择等决策记录。
- `configs/paper_defaults.yaml` 与 `configs/smoke/tsp_mock.yaml`。

### 验收标准

- 算法每一步都能映射到“论文页码/块 ID”或一个明确 ADR，不能出现无来源的隐藏默认值。
- 参数校验脚本能拒绝 `N<2`、`T<1`、无终止预算等无效配置。
- 团队能仅根据 spec 手工演算一代候选流，候选数量与预算账本一致。
- 未决问题都有 owner、影响等级和最晚决策阶段。

### 推送到 GitHub

分支 `stage/01-paper-spec`；提交上述 `docs/`、`configs/`、根目录 README 路线图；合并后打标签 `v0.1-paper-spec`。不提交论文 PDF，避免版权和大文件问题。

## 阶段 2：环境与基线搭建（1–2 周）

### 具体任务

1. 建立 Conda `environment.yml`，固定 Python、PyTorch、NumPy/SciPy、Pydantic、Hydra/OmegaConf、pytest、ruff、mypy；生成平台信息清单。
2. 实现 `Candidate`、`Population`、`EvaluationResult`、`BudgetLedger`、`RunManifest` 数据结构。
3. 实现 LLM provider 抽象和确定性的 Mock provider；支持 OpenAI-compatible endpoint，但不与单一厂商耦合。
4. 先实现最小 EoH：初始化、E1/E2、M1/M2、评估、Top-N；再写 LLM4AD_Next/EoH 适配器做交叉核验。
5. 建 TSP-50 最小 evaluator：固定训练实例、超时、缓存、seed、代码签名检查和子进程隔离。
6. 建 CLI、结构化日志、断点续跑与 GitHub Actions。

### V1 简化与升级

- V1 只支持 TSP 和串行评估；LLM 用 mock 即可跑全流程。
- 后续增加 Ray/多进程、五任务统一适配、容器级沙箱和失败自动归因。

### 关键交付物

- 可创建的 Conda 环境；可安装的 `roco_ebbo` 包。
- EoH MVP、TSP evaluator、Mock/OpenAI-compatible provider。
- 预算账本、run manifest、CI、单元测试。

### 验收标准

- 全新机器按 README 在 30 分钟内完成环境创建与 smoke run。
- `pytest -q` 全通过；CI 不需要密钥。
- 相同 seed + Mock provider 两次运行的候选哈希、分数和预算完全一致。
- 超时、语法错、签名错的候选不会中断种群运行；预算不会透支。
- EoH 在 TSP-50 上至少产生一个优于初始化中位数的有效候选。

### 推送到 GitHub

分支 `stage/02-eoh-mvp`；推送 `environment*.yml`、`pyproject.toml`、`src/.../core|llm|evolution|evaluation`、TSP 小型固定数据、tests、CI、`.env.example`；标签 `v0.2-eoh-mvp`。

## 阶段 3：角色代理与多轮协作实现（1–2 周）

### 具体任务

1. 定义统一 Agent 接口和四个独立策略；prompt 用 Jinja/YAML 版本化，不写在业务代码中。
2. 定义结构化消息：`Proposal`、`Critique`、`Revision`、`IntegrationDecision`，代码与解释分字段。
3. 实现 CollaborationEngine 状态机：抽样精英对 → 初评 → T 轮 Explorer/Exploiter → 每轮 Critic → Integrator。
4. 实现论文的精英偏置采样：`p_i ∝ 1/(i+1)^k`，`k=3.0`；第二个个体取相邻 `+1/+2` 且边界安全。
5. 实现 token 截断优先级、模型重试、JSON/代码解析与全部调用审计。
6. 加入 `no-critic`、`no-integrator`、`T∈{1..5}` 开关，为后续消融做准备。

### V1 简化与升级

- V1 四角色可共享同一基础模型，仅温度和 prompt 不同；消息严格按中心化状态机传递。
- 后续支持不同模型路由、并行双路、角色可信度、辩论式 Critic、多 Integrator 投票。

### 关键交付物

- 四角色实现、prompt 模板、输出 schema、状态机与序列图。
- 可重放的 mock 对话 fixture 和调用审计报告。
- `scripts/smoke/run_roco_tsp.ps1` 或等价 CLI 配置。

### 验收标准

- `T=3` 时状态机严格完成 3 个双路精炼轮次；任何角色失败都能降级或重试并留下事件。
- 所有消息通过 schema 校验；不得从自由文本中猜测分数字段。
- Mock 集成测试覆盖正常、超时、格式错、Integrator 失败四种路径。
- 一次真实小预算运行能输出可执行融合候选，且每个候选可追溯到父代与 prompt 版本。

### 推送到 GitHub

分支 `stage/03-role-collaboration`；推送 `agents/`、`collaboration/`、`prompts/roles/`、schema、fixtures、集成测试和协议文档；标签 `v0.3-roco-loop`。

## 阶段 4：反思与记忆机制实现（约 1 周）

### 具体任务

1. 短期反思：每轮 Critic 反馈绑定父代、子代、目标值、Δg、错误类别和采用结果。
2. LTReflect：每个角色每代把近期证据压缩为“有效策略、失败模式、适用条件、禁止重复项”，控制在短摘要内。
3. 跨代记忆：原始 `MemoryEvent` 追加写 JSONL；累计摘要单独版本化；支持从 checkpoint 恢复。
4. 检索：默认最近 K 条 + 贡献最大的成功/失败各一条；严格限制注入 token。
5. 记忆引导变异：对每个精英按 Explorer/Exploiter/Integrator 三个视角各生成一个候选，统一进入评估与 Top-N。
6. 建立记忆消融：无记忆、仅短期、短期+长期、完整跨代。

### V1 简化与升级

- V1 使用 JSONL + 单一累计摘要，不使用向量数据库；按最近性和 |Δg| 排序。
- 后续采用 SQLite/向量混合索引、负迁移检测、遗忘策略、任务相似度和记忆价值在线学习。

### 关键交付物

- `memory/` 模块、事件 schema、checkpoint/恢复、prompt 注入器。
- 三类 mutation prompt 与记忆消融配置。
- `docs/protocols/memory.md`，包含保留、检索、压缩、隐私和成本规则。

### 验收标准

- 每条反思都能回溯到实际分数变化；无评估结果的“自我感觉改进”不得写成成功经验。
- 中断后恢复的下一代候选、记忆摘要和预算与不中断运行一致。
- 上下文永不超过角色预算；截断决策可审计。
- 固定 mock 场景中，有记忆版本不再重复已标记失败的变异；消融开关确实改变检索路径。

### 推送到 GitHub

分支 `stage/04-reflection-memory`；推送 memory 模块、三类 prompt、checkpoint、消融配置、样例脱敏事件和测试；标签 `v0.4-memory`。真实 API 对话日志默认不提交。

## 阶段 5：实验对齐与复现验证（3–5 周）

### 具体任务

1. **先 TSP**：复刻训练 5 个 50 节点实例；测试每个规模 64 个实例；对齐 evaluator 迭代数和超时。
2. 白盒提示提供完整问题结构；黑盒提示只提供抽象边属性，避免把昂贵 oracle 黑盒混进本阶段。
3. 在同一模型、同一有效评估数、同一超时和 seed 下运行 EoH、ReEvo、RoCo。
4. 顺序复现：Table 3 消融 → TSP 白盒/黑盒 → MKP/OP/BPP/CVRP → GLS 扩展（可选）。
5. 每个主配置至少 3 seeds 用于与论文对齐；资源允许时扩到 10 seeds。报告均值、标准差、bootstrap 置信区间和配对检验。
6. 同时画四条成本曲线：最优值–有效评估、最优值–LLM call、最优值–token、最优值–墙钟时间。
7. 对数值差异做归因：模型版本、数据实例、预算口径、编译失败率、prompt 修正、并行顺序。

### V1 简化与升级

- V1 只承诺 TSP 的 L1/L2；其余四任务按 adapter 模式逐个加入。
- 后续补齐全表、更多 seed、公开模型、本地模型与跨模型稳健性。

### 关键交付物

- 五任务 adapter 与数据生成/下载校验脚本。
- 论文对齐配置、基线锁定版本、运行 manifests。
- `results/reproduction/summary.csv`、图表和 `docs/reproduction_report.md`。
- 失败候选率、token、费用、墙钟和预算使用率审计表。

### 验收标准

- **工程门槛**：每个实验均可从 manifest 重跑；数据 checksum、commit、环境、prompt、模型名和 seed 完整。
- **行为门槛**：完整 RoCo 在预注册 TSP 指标上优于或不劣于同预算 EoH 的中位结果；关键消融总体方向与论文一致。若不一致，必须形成可验证的差异报告，而非调参到“看起来一致”。
- **数值门槛**：第一轮以论文值相对误差 ≤5% 为诊断目标；确认数据和模型足够一致后再收紧至 1–3%。
- **公平门槛**：基线按相同 `valid_evals` 比较，同时公开 LLM calls/tokens；不得只用对 RoCo 有利的预算口径。

### 推送到 GitHub

分支 `stage/05-reproduction`；推送 benchmark adapter、配置、聚合脚本、小型汇总和报告；大体积运行日志/数据放 Release、对象存储或 DVC，仓库只留 checksum 与下载说明；标签 `v0.5-tsp-reproduced`、`v1.0-roco-reproduction`。

## 阶段 6：迁移到多智能体昂贵黑盒优化（3–5 周形成首版）

### 6.1 首选问题定义

先做“直接决策型”迁移，而不是用昂贵 oracle 反复评价 LLM 生成的完整优化器：

\[
\min_{x\in\mathcal X} f(x),\qquad
\mathcal D_t=\{(x_i,y_i)\}_{i=1}^{t},\quad y_i=f(x_i)+\epsilon_i
\]

同时约束真实评估预算 `B_eval`、LLM/token 预算 `B_llm`、墙钟预算 `B_time` 和并行容量 `q`。每一轮只有 Integrator 选中的少量点可以调用真实 oracle，其余候选只通过 surrogate/acquisition 评分。待直接型系统稳定后，再研究“外层进化优化器策略”的元优化版本。

### 6.2 迁移后的角色

| 角色 | 昂贵黑盒优化中的职责 |
|---|---|
| Explorer | 在高不确定区、未覆盖区域和不同表示空间提出多样候选 |
| Exploiter | 围绕 incumbent、可信局部模型和可行域提出低风险候选 |
| Critic | 检查 surrogate 校准、候选重复、约束风险、预期改进与成本；不直接伪造目标值 |
| Integrator | 在剩余预算与并行容量下选最终 batch，并决定探索/利用配额 |
| BudgetManager（确定性服务） | 记账、硬停止、角色调用配额、真实 oracle 权限；不得由 LLM 绕过 |

### 6.3 新增机制与任务

1. **共享 surrogate**：首版用 BoTorch/GPyTorch GP；高维或混合变量再扩展 RF/Deep Ensemble/HEBO 类模型。
2. **候选池而非直接评估**：Explorer/Exploiter 各给出候选及理由，确定性层做边界投影、去重和可行性检查。
3. **预算分配**：V1 固定 50/50 探索–利用并保留 10% 随机安全配额；V2 用 bandit/价值成本比动态分配角色调用与 oracle 名额。
4. **代理预测与早期剪枝**：用 acquisition、预测均值、不确定度、约束概率和多样性筛选；任何剪枝器必须保留最小探索概率，避免错误 surrogate 永久封死区域。
5. **异步与 pending points**：支持并行 oracle，采用 fantasization/local penalization，避免多个 agent 重复提议同一区域。
6. **通信成本控制**：传递结构化统计摘要，不传完整历史；连续两轮“预期增益/token”过低时提前停止协作。
7. **双记忆**：把“优化策略经验”和“具体样本数据”分开；前者可跨任务迁移，后者默认仅在当前任务使用。
8. **缓存与去重**：同一点或容差内近邻禁止重复真实评估，除非显式执行噪声复测。

### 6.4 实验阶梯

1. 无噪声合成：Branin、Hartmann、Ackley、Rosenbrock，维度 2/5/10/20。
2. 噪声、约束、混合变量与多峰；加入人工 sleep 模拟真实高耗时。
3. BBOB/COCO 或等价标准套件。
4. 一个真实昂贵案例，例如仿真超参数、工程设计或多智能体系统策略参数整定。

基线至少包括 Random/LHS、CMA-ES 或 DE、BoTorch qNEI/qUCB/TS、HEBO 类方法、单代理 LLM-BO，以及可运行的分布式/多代理 BO。公平比较必须固定真实 oracle 次数，而不是总候选数。

### V1 简化与升级

- V1：单进程、单任务、连续变量、无约束、单 GP、固定角色配额、同步 batch。
- V2：异步、多保真、约束/混合变量、动态 budget bandit、surrogate ensemble、跨任务元记忆。
- V3：去中心化 agent、通信延迟/丢包、隐私数据、真实多智能体系统协同优化。

### 关键交付物

- `ebbo/oracle.py`、`surrogate.py`、`acquisition.py`、`budget_manager.py`、`scheduler.py`。
- 昂贵黑盒的角色 prompt 与 typed message schema。
- 合成 benchmark、基线、预算曲线、消融和成本–性能 Pareto 报告。
- 从 RoCo-AHD 到 RoCo-EBBO 的设计论文草稿/技术报告。

### 验收标准

- **安全性**：任何运行都不能超过 `B_eval/B_llm/B_time`；崩溃恢复不重复扣款或重复评估。
- **算法性**：每个真实评估点都有“由谁提出、为何保留、为何淘汰其他点”的可追踪记录。
- **基准性**：先在不少于 20 个合成函数×seed 组合上报告 normalized simple regret/AUC；真实昂贵任务至少 5 seeds。
- **研究成功判据**：在预注册任务子集、相同 `B_eval` 下，相对最强非 LLM BO 基线获得统计可信的 regret/AUC 改进，或形成清晰的“性能–token/墙钟”Pareto 优势。若只增加成本而无收益，应如实判定该机制失败。
- **消融性**：预算调度、surrogate 剪枝、动态停止、长期记忆分别可关闭并量化贡献。

### 推送到 GitHub

分支 `stage/06-ebbo`；推送 `ebbo/`、合成 benchmark、BBO 配置、预算测试、基线脚本、报告；标签 `v1.1-ebbo-mvp`。真实私有数据、许可证受限仿真器和 API 密钥不入库。

## 3. 推荐里程碑与停止条件

| 周期 | 里程碑 | 继续下一阶段的硬条件 |
|---|---|---|
| 第 1 周 | Stage 1 | spec、缺口表和预算术语通过审查 |
| 第 2–3 周 | Stage 2 | Conda + mock EoH + TSP evaluator 可重复 |
| 第 4–5 周 | Stage 3 | 四角色 T=3 状态机和审计链完整 |
| 第 6 周 | Stage 4 | 记忆可恢复，Δg 证据可追踪 |
| 第 7–11 周 | Stage 5 | 至少 TSP 达到 L1/L2 复现 |
| 第 12–16 周 | Stage 6 | EBBO MVP 不超预算并完成公平基线比较 |

若 Stage 5 的 TSP 连行为趋势都不一致，先暂停扩展五任务，优先排查 evaluator、预算口径、prompt 歧义和无效代码处理；不要用更多 API 调用掩盖实现问题。若 Stage 6 的 LLM 版本在等真实评估预算下持续输给 qNEI/TS，则保留 RoCo 的多角色诊断与预算调度，减少 LLM 参与频率，而不是继续扩大 agent 数量。

## 4. GitHub 工作方式

每阶段一个短生命周期分支和 PR；PR 模板要求填写：论文/ADR 依据、预算影响、复现实验、兼容性和回滚方式。Release 只包含代码、配置、汇总表、图和 manifests。建议启用：

- branch protection、CI 必须通过、禁止 secret；
- Issues 标签：`paper-gap`、`reproduction`、`baseline`、`ebbo`、`experiment-cost`；
- 每个实验配置生成不可变 run ID；结果文件记录 commit SHA 与环境导出；
- `results/` 只保存小型可审计产物，大文件外置并提供 checksum。

## 5. 立即可执行的前三个动作

1. 将阶段 1 的 spec、gap registry、ADR 和两个 YAML preset 作为首个 PR，而不是直接写四角色代码。
2. 在 Linux 或 Windows 的 WSL2 中，用 Conda 建立 Python 3.11 主环境，先完成 MockLLM + TSP evaluator + 最小 EoH；真实 API 接入应排在确定性测试之后。只有直接运行当前 LLM4AD_Next 时才另建 Python 3.12 环境。
3. 预注册 TSP 复现协议与预算账本，再实现四角色；这样后续每个模块都能用相同 budget ledger 做公平消融。

## 6. 参考实现与相关方向

- RoCo 论文：<https://arxiv.org/abs/2512.03762>
- LLM4AD_Next：<https://github.com/Optima-CityU/LLM4AD_Next>
- ReEvo：<https://github.com/ai4co/reevo>
- EoH：<https://arxiv.org/abs/2401.02051>
- HSEvo：<https://github.com/datphamvn/HSEvo>
- MCTS-AHD：<https://github.com/zz1358m/MCTS-AHD-master>
- BoTorch：<https://github.com/pytorch/botorch>
- HEBO：<https://github.com/huawei-noah/HEBO>
- MAroBO：<https://github.com/Shyam4801/marobo>
- LLM-in-the-Loop BO：<https://github.com/UMDataScienceLab/LLM-in-the-Loop-BO>
