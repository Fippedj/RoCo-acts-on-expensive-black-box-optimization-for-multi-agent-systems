# AI 项目状态、审计与任务提示词规划手册

> 用途：把本文件单独交给一个新的 AI 会话，使它能理解仓库现状、区分已提交与未提交工作，并帮助用户设计后续实现任务的提示词。
>
> 快照日期：2026-09-19（Asia/Shanghai）。本文件是状态快照，不是 Git 或测试结果的替代品；新会话必须先用只读命令复核。

## 0. 给新 AI 会话的工作规则

收到本文件后，先执行或要求实现会话执行以下只读检查：

```bash
pwd
git status --short --branch
git branch -vv
git log --graph --decorate --oneline --all -12
git diff --check
```

解释状态时遵循以下优先级：

1. 当前 Git、源码、配置和测试的实时结果；
2. 已接受的 ADR 与 `docs/paper_spec/`；
3. 本文件记录的快照；
4. 早期 roadmap 中尚未被 ADR 收敛的设想。

本会话的推荐职责是“状态解释与任务提示词设计”，不是默认直接改代码。设计每个任务时必须明确：目标、允许修改范围、明确不做内容、兼容性要求、预算/安全边界、验收命令、Git 操作限制和交付报告格式。

不要默认授权以下动作：真实 API/网络调用、使用密钥、花费预算、提交、推送、删除运行数据、改变分支历史或实现下一阶段之外的功能。

## 1. 机器可读状态摘要

```yaml
snapshot:
  date: 2026-09-20
  repository: /home/fj/RoCo-BO/RoCo-ebbo-stage4
  origin: https://github.com/Fippedj/RoCo-acts-on-expensive-black-box-optimization-for-multi-agent-systems.git
  branch: stage/04-reflection-memory
  stage4_parent: f6f3e1dd19427704971d443f28e894ce57af3676
  current_head: "run: git rev-parse HEAD"
  current_head_subject: "run: git log -1 --format=%s"
  upstream: origin/stage/04-reflection-memory
  upstream_distance: "run: git rev-list --left-right --count HEAD...@{upstream}"
  stage3_implementation_commit: 2ce66a4f66c0e446fa8b44a729783074cc13064a
  stage3_publication_commit: f6f3e1dd19427704971d443f28e894ce57af3676
  stage4_design_commit: cf1e06b5fcaac29a4c17694e2f1f336e784a9521
  stage4_design_committed_locally: true
  stage4_design_pushed: true
  stage4_p3a_commit: a0b24b118870633855f14553e06c0989c92a3aac
  stage4_p3a_committed_locally: true
  stage4_p3a_push_status: pending_normal_push
  stage4_runtime_published: false  # P3b/P4 are still absent
  expected_worktree_clean: true
  agents_md_present: false
  codegraph_present: false
  network_required: false
  real_llm_enabled: false
  current_provider: mock-only
  current_benchmark: deterministic TSP-20 smoke
  python_target: "3.11"
  validation_environment: roco-dev
  last_validation:
    pytest: "65 passed"
    ruff_check: passed
    ruff_format_check: passed
    mypy: "21 source files, no issues"
    doctor: "stage3-roco-ready"
    stage2_smoke: "12 llm_calls, 12 valid_evals, budget_reached=false"
    stage3_smoke: "18 llm_calls, 13 valid_evals, budget_reached=false"
    git_diff_check: passed
```

重要：Stage 4 设计已由 `cf1e06b` 冻结并发布。P3a 事实层与恢复底座已在本地提交
`a0b24b1`，并通过 65 个测试、Ruff、mypy、doctor 和两个既有 smoke；本状态文档提交后
将与该代码检查点一起正常推送。精确 HEAD、远端同步状态和工作区必须用本文件开头的
只读命令复核，不能把 P3a 已验证误写成整个 Stage 4 已完成。

## 2. 分支和 worktree 关系

当前提交关系是线性的：

```text
main / origin/main
  2b19788  style: normalize ignore rules
      |
stage/01-paper-spec / origin/stage/01-paper-spec
  e95f7f7  docs: add Stage 1 paper specification
      |
stage/02-eoh-mvp / origin/stage/02-eoh-mvp
  96eec77  feat: add deterministic EoH smoke baseline
      |
  2ce66a4  feat: add deterministic RoCo role collaboration
      |
stage/03-role-collaboration / origin/stage/03-role-collaboration
  f6f3e1d  docs: record Stage 3 publication status
      |
stage/04-reflection-memory / origin/stage/04-reflection-memory
  cf1e06b  docs: freeze Stage 4 memory design
      |
  21b0ca6  docs: record Stage 4 design publication status
      |
  a0b24b1  feat: add Stage 4 P3a memory foundation
```

`stage/02-eoh-mvp` 还在另一个 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo
```

Stage 3 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage3
```

当前 Stage 4 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage4
```

当前分支 `stage/04-reflection-memory` 跟踪同名远端分支。不要在文档中固定自引用的 HEAD
或 ahead/behind；用 `git rev-parse HEAD`、`git log -1 --format=%s` 和
`git rev-list --left-right --count HEAD...@{upstream}` 获取实时值。P3a 正常推送后，工作区
应无未提交修改。

本机 `roco-dev` 环境中的 editable install 曾指向 Stage 2 的兄弟 worktree。为确保验证加载当前源码，最近一次验证先设置了：

```bash
export PYTHONPATH="$PWD/src"
```

长期修复方案是在用户明确允许时，于当前 worktree 激活 `roco-dev` 后重新执行 `python -m pip install -e '.[dev,llm]'`，然后确认 `python -c 'import roco_ebbo; print(roco_ebbo.__file__)'` 指向本目录。该环境变更不应由规划会话擅自执行。

## 3. Stage 3 提交文件清单

以下文件共同组成 Stage 3 检查点。提交后的正常状态应是这些路径均无未提交 diff；
若实时 `git status` 显示变化，必须把它们视为提交后的新工作，不能按本清单覆盖。

### 3.1 Stage 2 跟踪文件上的修改

```text
README.md
configs/paper_defaults.yaml
configs/smoke/tsp_mock.yaml
docs/START_HERE.md
docs/gap_registry.md
src/roco_ebbo/__main__.py
src/roco_ebbo/benchmarks/tsp.py
src/roco_ebbo/cli.py
src/roco_ebbo/core/models.py
src/roco_ebbo/evaluation/tsp.py
src/roco_ebbo/evolution/__init__.py
src/roco_ebbo/evolution/engine.py
src/roco_ebbo/llm/__init__.py
src/roco_ebbo/llm/provider.py
src/roco_ebbo/smoke.py
tests/test_cli.py
```

### 3.2 Stage 3 新文件

```text
configs/smoke/tsp_roco_mock.yaml
docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md
docs/adrs/0003-stage3-roco-collaboration.md
src/roco_ebbo/evolution/collaboration.py
src/roco_ebbo/llm/prompts.py
tests/integration/test_roco_smoke.py
tests/unit/test_collaboration.py
```

### 3.3 不属于待提交源码的运行产物

smoke 会在被 Git 忽略的 `runs/` 下生成 manifest、summary、events 和 collaboration trace。它们用于本地审计，不应默认加入提交。原始 LLM 对话、密钥、下载数据和大型运行日志也不得提交。

## 4. 项目目标和阶段定义

项目总目标分两部分：

1. 方法级复现 RoCo：角色协作、反思、记忆变异、EoH 合并和可审计预算；
2. 在复现稳定后，把角色协作思想迁移到多智能体昂贵黑盒优化（EBBO）。

应始终区分：论文中的 black-box prompt 是“不向 LLM 暴露问题内部语义”，而 EBBO 的黑盒是“只能通过昂贵 oracle 获得目标值”。Stage 6 不是简单替换 benchmark。

## 5. 开发完成度

完成度必须按口径说明，不能只给一个模糊百分比。

| 阶段 | Git 状态 | 当前结果 | 对该阶段最近明确范围的完成度 |
|---|---|---|---:|
| Stage 1：论文规格 | 已提交并有远端分支 | algorithm、参数登记、缺口表、ADR-0001 | 100% |
| Stage 2：确定性 EoH MVP | 已提交并有远端分支 | Mock、预算、Candidate/Population、TSP-20 evaluator、CLI smoke | 100% |
| Stage 3：四角色协作 | 已提交并发布远端分支 | 四角色、T 轮状态机、失败降级、trace、独立 smoke、测试与 ADR-0003 | 100% |
| Stage 4：反思与跨代记忆 | 设计已发布；P3a 已提交并验证、待正常推送；P3b/P4 未实现 | ADR-0004、memory 可执行规格、P3a facts/recovery 底座 | 设计 100%，P3a 100%，P3b/P4 0% |
| Stage 5：论文实验对齐 | 未实现 | 只有路线图和 TSP-20 开发 evaluator | 0% |
| Stage 6：多智能体 EBBO | 未实现 | 只有研究分析和路线图 | 0% |

以“六阶段是否具有可运行实现”粗略计数，目前完成前三阶段，约为 3/6；但这不等于研究工作量完成 50%，因为 Stage 4–6 的实验与方法研究明显更重。

另一个必须说明的口径：相对于早期 roadmap 中更宽的 Stage 3 清单，当前约完成 70%–80%。roadmap 还提到 prompt 外置为 Jinja/YAML、上下文截断、修复重试、`no-critic`/`no-integrator` 消融和真实小预算运行；这些不在最近一次明确 Stage 3 任务范围内，且真实 API 被明确禁止，因此不是当前验收失败，而是后续候选任务。

## 6. 已实现架构

### 6.1 Stage 1：规格和决策

- `docs/paper_spec/algorithm.md`：从 `G0_VALIDATE` 到 `G14_COMMIT` 的完整论文状态机规格。
- `docs/paper_spec/parameter_registry.md`：论文参数、证据和工程默认值。
- `docs/adrs/0001-budget-and-memory-v1.md`：预算、长期记忆的预先决策。
- `docs/gap_registry.md`：论文明确、合理推断、自行设计项。

### 6.2 Stage 2：确定性 EoH 基线

- `Candidate`、`EvaluationResult`、`BudgetLedger`、`RunManifest`。
- `Population.select_top_n()`：只接收有限有效分数，按 `(score, candidate_id)` 确定性排序。
- E1/E2/M1/M2：初始化和每代候选生成。
- `MockLLMProvider`：seed 驱动、离线、结构化输出。
- TSP-20：对称欧氏距离矩阵、闭环 tour score。
- evaluator：AST/签名检查、受限 builtins、spawn 子进程和单候选 timeout。
- CLI：doctor、smoke、manifest、summary 和 events。
- Stage 2 smoke 固定结果：`N=4`、`G=2`、12 calls、12 valid evaluations。

安全边界：当前 evaluator 只是开发期防误用机制，不是容器、独立 OS 用户、seccomp 或网络/文件系统隔离。只能执行可信本地或 Mock 代码。

### 6.3 Stage 3：四角色和协作状态机

角色与温度：

| 角色 | 责任 | 默认温度 |
|---|---|---:|
| Explorer | 强调结构新颖性和多样性 | 1.3 |
| Exploiter | 对有希望方案做保守精炼 | 0.8 |
| Critic | 只根据已验证目标值比较并提出反馈 | 1.0 |
| Integrator | 融合最终 Explorer/Exploiter 候选和反馈 | 1.0 |

关键接口：

- `src/roco_ebbo/llm/prompts.py`：`RoCoRole`、`ROLE_PROMPTS`、`ROLE_TEMPERATURES`、prompt version。
- `src/roco_ebbo/llm/provider.py`：`RoleRequest`、`RoleResponse`、`RoleLLMProvider` 和角色感知 Mock。
- `src/roco_ebbo/evolution/collaboration.py`：`RoCoCollaborator`、event/trace/outcome。
- `src/roco_ebbo/evolution/engine.py`：可选 collaborator 与统一 Top-N。
- `src/roco_ebbo/smoke.py`：`evolution.mode: eoh|roco` 分派。

每代实际流程：

```text
已评估 P_g
  -> 生成 E1/E2/M1/M2 offspring
  -> 从 P_g 按 1/(rank+1)^k 采样相邻精英对
  -> initial Critic (round 0)
  -> for t in 1..T:
       Explorer proposal -> AST/evaluator -> branch Critic
       Exploiter proposal -> AST/evaluator -> branch Critic
  -> one final Integrator -> AST/evaluator
  -> P_g + EoH + 全部有效 RoCo 候选
  -> deterministic Top-N
```

实现按固定串行事件顺序记录，但同一轮 Explorer 和 Exploiter 都只读取上一轮自身状态/反馈，不读取对方本轮输出。

正常每代角色调用数：

```text
Critic: 1 + 2T
Explorer: T
Exploiter: T
Integrator: 1
total role calls: 4T + 2
generated/evaluated RoCo candidates: 2T + 1
```

论文默认 `T=3`，对应 14 次角色调用、7 个 RoCo 候选。当前独立 RoCo smoke 使用 `T=2`，加上初始化和 EoH 后为 18 calls、13 valid evaluations。

### 6.4 失败降级

- 非法 RoleResponse：`invalid_output`，不猜测自由文本。
- 无效、超时或 evaluator 失败候选：`invalid_candidate`，不进 Top-N，分支保留上一有效候选。
- Critic 失败：保留旧反馈继续。
- Integrator 失败：跳过融合候选，已经完成的候选仍可选择。
- 硬预算耗尽：`budget_exhausted`，停止发起后续消费动作并安全收尾。
- 未知类型的角色输出也被当作结构错误，而不是触发属性访问崩溃。

### 6.5 generation-local trace

RoCo CLI 写 `collaboration_trace.jsonl`，每代一个 `roco-collaboration-trace-v1` 对象。顶层包含 generation、精英对及排名、采样 seed/权重、请求/完成轮数、预算停止状态和最终 selected IDs。事件包含：

```text
event_id
role / action / target_branch / round
temperature / prompt_version
input_candidates / input_feedback
output_candidate / output_feedback
evaluation
budget_before / budget_after / budget_delta
status / error_type / error_message
```

该 trace 是运行审计，不是长期记忆。runtime 和 wall-clock 可随机器调度变化；Mock 重放承诺候选内容/ID、角色顺序、分数和非时间预算一致，不承诺日志逐字节一致。

## 7. 当前审计结论

### 7.1 在最近明确 Stage 3 范围内通过的项目

- 四角色都有独立且版本化的 prompt 契约。
- `collaboration_rounds` 只在显式 `mode=roco` 时执行；旧配置缺省仍是 EoH。
- 角色默认温度和 `T=3` 默认已在实现中固化，smoke 可显式降低 T。
- 所有生成的可执行候选复用现有 evaluator 和预算账本。
- 非法输出、无效候选和角色预算耗尽都有结构化测试。
- 同 seed 的角色顺序、候选、ID、分数和去除 runtime 后的 trace 可重放。
- CLI 确实生成每代 trace，Stage 2 smoke 保持 12/12 计数。
- provider 抛异常、Integrator 非法输出和 RoCo 候选 timeout 都会降级并继续。
- 默认 `T=3` 已有精确的 14 calls/7 candidates 测试，多代 trace/event ID/采样流可重放。
- call 与 valid-eval 两种预算在协作中途耗尽时都能保存 trace 并完成选择。
- 配置拒绝 NaN/Infinity；Stage 3 明确拒绝与当前 prompt 不一致的最大化模式。
- ADR-0003 明确了论文对应、工程简化和 Stage 4 边界。
- 未发现当前范围内阻止提交的功能性错误。

### 7.2 剩余非阻断风险

提交前加固已经覆盖 provider 异常、Integrator 失败、timeout、默认 T=3、多代 trace、
两类预算中断、非有限配置和最小化契约。剩余项属于后续耐久性或真实 provider 范围：

1. 决定 trace 是否需要逐代立即落盘/原子写。目前 CLI 在 engine 完整返回后统一写文件；正常运行满足每代可序列化 trace，但进程崩溃时没有逐代耐久性。
2. provider 是否对“已接受但抛错的调用”正确计费依赖具体 provider 实现；Mock 异常路径已有测试，真实 provider 接入时仍必须使用 fake transport 复核。
3. 最大化任务尚不支持；进入实现前需要版本化 objective contract，并同步 prompt、Mock Critic、排序和测试。

### 7.3 roadmap 与当前实现的差异

以下差异已经知道，不应由新 AI 误判为隐蔽完成：

- roadmap 建议 Jinja/YAML prompt；当前用版本化 Python 常量。
- roadmap 曾建议 `Proposal/Critique/Revision/IntegrationDecision` 多 schema；当前使用统一 `RoleRequest/RoleResponse`。
- roadmap 提到相邻 `+1/+2`；当前可执行规格与实现使用边界安全的相邻 `±1`，仍需 PDF 逐式复核。
- 没有上下文 token 截断、自动修复重试或 no-role 消融开关。
- 没有真实 OpenAI-compatible provider；最近 Stage 3 任务明确要求离线且禁止真实 API。
- 没有 checkpoint/resume、缓存、并行调度或容器级沙箱。

修改这些行为前必须先更新 ADR/规格及预算公式，不能静默改变现有 smoke 回归。

## 8. 明确未实现的功能

### Stage 4

- 已完成并发布的设计：`roco-memory-event-v1`、角色摘要、minimize `delta_g`、K=5 的
  3/2 成败检索、每精英 E/X/I 三次 mutation、代级 segment/commit/checkpoint 与恢复不变量；
- 已提交、已验证、待正常推送的 P3a：严格 memory schema、Stage 3 trace 纯转换器、
  不可变 generation segment、commit-last 校验、checkpoint 序列化与恢复读取底座；
  代码提交为 `a0b24b1`，验证为 65 passed、Ruff check/format、mypy、doctor、Stage 2
  12/12 smoke、Stage 3 T=2 18/13 smoke 与 `git diff --check` 均通过；
- 当前下一开发任务 P3b：LTReflect/角色摘要运行时、K=5 检索、可审计 prompt 截断与
  memory-guided mutation 接入；
- P4 仍需端到端恢复与 memory/no-memory 消融验收；整个 Stage 4 尚未完成。

### Stage 5

- 真实模型 provider 和费用表；
- 论文 TSP-50/TSP-100/TSP-200 数据与训练/测试协议；
- white-box/black-box prompt 两套实验；
- ReEvo、EoH 等预算公平基线；
- MKP、OP、BPP、CVRP 和 GLS；
- 多 seed 统计、置信区间、结果聚合和论文数值报告。

### Stage 6

- 昂贵 oracle 抽象；
- surrogate、acquisition、posterior 和不确定性校准；
- 多 agent 区域划分和共享 posterior；
- 异步 worker、pending evaluation、成本/失败感知调度；
- EBBO benchmark 和 regret 指标。

## 9. 推荐后续任务顺序

```text
P0  Stage 3 最终审计/小范围加固（已完成）
  -> P1  Stage 3 提交并发布远端分支（已完成）
  -> P2  Stage 4 可执行规格和 ADR-0004（已完成、已提交并发布）
  -> P3a memory schema/trace 转换/segment store/commit-last/checkpoint 恢复底座（已提交、已验证、待正常推送）
  -> P3b 角色摘要/K=5 检索/可审计 prompt 截断/memory mutation 接入（当前下一开发任务）
  -> P4  Stage 4 确定性恢复/消融验收
  -> P5  真实 provider 的独立小预算接入
  -> P6  Stage 5 TSP 论文实验对齐
  -> P7  其他 COP 和统计复现
  -> P8  Stage 6 EBBO 设计规格
  -> P9  EBBO 最小基线和角色控制层
```

不要把 P3a、P3b、P5 和 P6 合成一次任务：事实/恢复底座、运行时记忆接入、真实 API
风险和论文实验协议应该分别审查。

## 10. 通用任务提示词模板

给实现 AI 的每次提示词建议采用以下结构：

```text
你正在仓库 <absolute-path> 的 <branch> 分支工作。

先阅读：
- docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md
- 与本任务有关的 ADR、paper_spec、源码、配置和测试
- 若存在 AGENTS.md 或 .codegraph/，按其规则执行

先用只读命令核对当前分支、HEAD、工作区和已有改动；不得覆盖用户未提交工作。
先输出简短实现方案，再开始修改。

目标：
<一个可验证的目标>

范围：
- <允许改动 1>
- <允许改动 2>

明确不做：
- <下一阶段功能>
- <真实 API/外部副作用等>

兼容性与不变量：
- 保持 Stage 2 smoke 的 12 calls / 12 valid evaluations
- 所有候选继续经过 AST、子进程 evaluator、timeout 和 BudgetLedger
- 保持 seed、稳定 candidate ID 和结构化失败
- 不把运行 trace 冒充长期记忆

验收：
<单元/集成行为断言>

验证命令：
python -m pytest
ruff check src tests
ruff format --check src tests
mypy src/roco_ebbo
python -m roco_ebbo doctor
python -m roco_ebbo smoke --config configs/smoke/tsp_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_roco_mock.yaml
git diff --check

Git 限制：
- 未明确授权时不要暂存、commit、push、rebase 或改写历史

最终报告：
- 架构与关键决策
- 变更文件
- 测试结果
- 论文对应与工程简化
- 未实现内容/风险
- 建议提交清单
```

## 11. 可直接复制的后续提示词

### 11.1 Prompt A：Stage 3 提交前最终加固（当前已完成，保留作回归模板）

```text
你正在 `/home/fj/RoCo-BO/RoCo-ebbo-stage3` 的 `stage/03-role-collaboration` 分支工作。先完整阅读 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md`、ADR-0003、Stage 3 源码与测试，并核对当前未提交改动。不要覆盖或丢弃已有工作。

目标：对现有 Stage 3 做提交前的小范围审计和加固，不重构已通过的架构。

至少检查并在确有缺口时补测试/最小修复：provider 抛异常、Integrator 失败、RoCo 候选 timeout、默认 T=3、多代 trace、协作中途不同预算耗尽、配置 NaN/Infinity。检查 `minimize` 契约是否会给未来调用者造成误导，并以最小改动消除不一致或明确限制。

保持 `mode=eoh` 的 Stage 2 结果严格为 12 calls/12 valid evaluations；保持 RoCo T=2 smoke 为 18 calls/13 valid evaluations。不得接入真实 API、长期记忆、自动重试、其他 benchmark 或 EBBO。所有失败必须变成结构化 trace，不能让 run 崩溃。

执行完整 pytest、Ruff、mypy、doctor、两个 smoke 和 git diff --check。不要暂存、commit 或 push。最后给出是否“可提交”的明确结论和剩余非阻断风险。
```

### 11.2 Prompt B：仅提交 Stage 3 检查点（已完成，保留作流程模板）

仅当用户已经审核 diff 并明确希望创建提交时使用：

```text
先阅读 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md` 并核对 `stage/03-role-collaboration` 当前状态。只处理已经完成并通过验证的 Stage 3 文件，不加入 `runs/`、密钥、原始对话或无关文件。

重新执行完整验证；若任一项失败则停止，不提交。若全部通过，列出将暂存的精确文件，请确认它们只属于 Stage 3，然后创建一个非 amend 提交，建议 message：`feat: add deterministic RoCo role collaboration`。

不要 push，不创建 tag，不 rebase，不修改其他分支。最后报告 commit SHA、文件清单、验证结果和仍未实现的 Stage 4 边界。
```

### 11.3 Prompt C：Stage 4 规格与 ADR（已完成，保留作设计模板）

```text
在开始 Stage 4 编码前，基于 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md`、ADR-0001/0003、paper_spec 和 gap_registry，设计可执行的 Stage 4 反思与记忆规格。本任务只写文档、schema 示例和测试计划，不实现 memory 代码。

必须决定：MemoryEvent/RoleMemorySummary 字段；delta_g 正值代表改进的方向归一化；哪些 Stage 3 trace 事件能转成记忆；append-only JSONL 的提交/恢复语义；最近 K=5 的确定性检索；成功/失败事件平衡；摘要版本/hash；token 截断优先级；每个精英三角色 memory-guided mutation；预算公式；去重与缓存；隐私和日志脱敏；崩溃恢复不变量。

新增 ADR-0004 和 `docs/paper_spec/memory.md`，更新 gap registry 与配置注释。明确区分论文事实、合理推断和工程决定。不得实现代码、真实 API、向量库、其他 benchmark 或 EBBO。最后输出可直接交给实现 AI 的 Stage 4 编码提示词。
```

### 11.4 Prompt D：Stage 4 P3a 事实层与恢复底座（已完成，保留作实现模板）

```text
你正在 `/home/fj/RoCo-BO/RoCo-ebbo-stage4` 的 `stage/04-reflection-memory` 分支工作。

先完整阅读 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md`、ADR-0001/0003/0004、
`docs/paper_spec/memory.md`、gap registry，以及 Stage 3 的 engine/provider/evaluator/trace、
预算、配置和测试。若存在 AGENTS.md 或 `.codegraph/`，先按其规则执行。核对分支、HEAD
和未提交改动，不得覆盖已有工作；先输出简短实现方案。

只按已冻结的 Stage 4 schema 实现可脱离运行时 mutation 独立测试的事实层与恢复底座：
严格 JSON-safe schema、Stage 3 generation-local trace 的纯转换器、不可变 generation
segment、SHA-256 manifest、commit-last 原子发布，以及 checkpoint 序列化和恢复读取接口。

要求：复用 Candidate、Population、BudgetLedger、Mock provider 和 Stage 3 trace；实现
`roco-memory-event-v1` 与角色摘要/检查点数据模型；最小化
`delta_g=before-after`；稳定 event ID；有限文本清理；每代不可变 JSONL segment 与
commit-last 哈希校验；显式 JSON-safe 的随机/Mock provider snapshot；只从连续有效 commit
恢复；缺 commit、坏 hash、临时文件和孤儿工件必须忽略并报告；已提交 segment 不得改写，
相同内容重提幂等，内容冲突 fail closed。

保持 Stage 2 smoke 12 calls/12 valid evaluations 和 Stage 3 T=2 smoke 18 calls/13 valid
evaluations 完全回归。至少测试 schema round-trip、非有限数拒绝、文本清理、minimize
delta、稳定 ID、E/X/I 成功与失败 trace 映射、selected IDs 回填、正常写读、半写/坏哈希/
缺 commit、非连续 generation、重提交冲突及 population/账本 checkpoint 恢复。

不得把 memory 接入 engine generation 路径，也不得实现 LTReflect/provider 新调用、K=5
检索、prompt 截断、memory mutation、真实 API、向量库、自动修复、缓存/去重、其他
benchmark、最大化 objective 或 EBBO。完成后不要暂存、commit、push；执行完整 pytest、
Ruff、mypy、doctor、两个既有 smoke 和 `git diff --check`。P3a 不应新增 LLM calls、
generated candidates 或 valid evaluations。
```

### 11.5 Prompt E：真实 provider 独立接入

此任务必须晚于 Mock + memory 路径稳定，并由用户明确授权。首次任务仍应禁止真实付费调用：

```text
为现有 LLMProvider/RoleLLMProvider 设计并实现 OpenAI-compatible adapter，但本任务不得发起真实网络请求、不得读取或输出真实密钥、不得产生费用。

使用依赖注入和 fake transport 测试：请求 schema、角色温度、timeout、重试上限、JSON 解析、token/费用记账、错误分类、模型/价格表版本、上下文截断和敏感字段脱敏。Mock 仍是默认 provider，CI 必须完全离线。没有显式 `provider: openai-compatible` 和环境变量时不得初始化网络客户端。

更新安全文档和独立配置示例，但 `.env` 与真实响应不得提交。保持所有现有 smoke 精确回归。不要实际调用 API、不要 commit/push。
```

### 11.6 Prompt F：Stage 5 TSP 复现实验准备

```text
先做 Stage 5 的 TSP-only 实验协议与 evaluator 扩展，不接入 MKP/OP/BPP/CVRP，也不运行昂贵真实实验。

核验论文 TSP 数据规模、训练/测试实例数、white-box/black-box prompt、timeout 和预算证据；不能确认的值登记为缺口。实现数据 checksum、TSP-50/100/200 配置、训练/测试分离、聚合 schema、3-seed dry-run 和 EoH/RoCo 等预算比较接口。结果必须同时按 valid_evals、llm_calls、tokens 和 wall time 报告。

先用 Mock/fake provider 完成 dry-run；真实模型实验另行授权。不得把论文 black-box prompt 写成昂贵 oracle 黑盒，不实现 EBBO。保持 Stage 2/3/4 smoke 回归，不 commit/push。
```

### 11.7 Prompt G：Stage 6 EBBO 设计（只设计）

```text
基于 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md` 和现有 RoCo-AHD 结果，设计 Stage 6 的多智能体昂贵黑盒优化架构，但本任务不编码。

明确问题定义、oracle budget、噪声/失败/约束、共享 posterior、异步 pending points 和 wall-clock/cost；将角色重新定义为 global explorer、local exploiter、model critic、resource integrator。Integrator 只能在 surrogate/acquisition 产生的统计候选池中选择或调度，不能让自然语言判断直接消耗昂贵 oracle。

给出最小基线（单 agent GP + EI/UCB/TS）、多 agent 对照、固定 oracle 预算、公平指标、消融矩阵、模块接口、ADR 和分阶段实现提示词。不要声称 RoCo 论文已经证明 EBBO 有效，不实现真实实验或调用外部服务。
```

## 12. 为每个新任务设计提示词时的检查表

规划 AI 在输出提示词前应回答：

- 任务属于哪个 Stage？是否意外跨到下一阶段？
- 当前目标是设计、实现、诊断、审查、实验还是 Git 操作？
- 哪些文件和接口可以修改？哪些必须保持兼容？
- 是否会使用真实网络、密钥、付费 API 或昂贵 oracle？如果会，是否有明确授权和硬预算？
- 对 `llm_calls`、tokens、generated candidates、valid evals、cost、wall time 的影响是什么？
- 是否改变 candidate ID、seed 派生、Top-N、失败语义或 trace schema？若改变，是否需要新 ADR/schema version？
- 是否保留 Stage 2 12/12 和当前 Stage 3 18/13 smoke 回归？
- 是否需要迁移旧日志/checkpoint？
- 测试是否覆盖正常、格式错、代码无效、timeout、provider error、预算耗尽和重放？
- 最终是否明确禁止未经授权的 commit/push？

## 13. 当前最推荐的下一条提示词

Prompt A、Prompt B、Prompt C 和 Prompt D 均已完成；Stage 4 设计已由 `cf1e06b` 冻结并
发布，P3a 事实层与恢复底座已由 `a0b24b1` 提交并通过完整质量门禁，待与本状态文档一起
正常推送。当前下一开发任务是 P3b：角色摘要运行时、K=5 检索、可审计 prompt 截断和
memory mutation 接入。P4 的端到端恢复与消融验收仍在其后；不得把 P3a 误写成整个
Stage 4 完成。
