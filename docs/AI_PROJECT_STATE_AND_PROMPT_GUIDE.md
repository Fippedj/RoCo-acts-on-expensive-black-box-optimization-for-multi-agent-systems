# AI 项目状态、审计与任务提示词规划手册

> 用途：把本文件单独交给一个新的 AI 会话，使它能理解仓库现状、区分已提交与未提交工作，并帮助用户设计后续实现任务的提示词。
>
> 快照日期：2026-09-24（Asia/Shanghai）。本文件是状态快照，不是 Git 或测试结果的替代品；新会话必须先用只读命令复核。

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
  date: 2026-09-24
  repository: /home/fj/RoCo-BO/RoCo-ebbo-stage6
  origin: https://github.com/Fippedj/RoCo-acts-on-expensive-black-box-optimization-for-multi-agent-systems.git
  branch: stage/06-ebbo-design
  stage4_parent: f6f3e1dd19427704971d443f28e894ce57af3676
  stage5_baseline: 59c335757b65935b29b7141ef6f0e6d338eb3603
  current_head: "run: git rev-parse HEAD"
  current_head_subject: "run: git log -1 --format=%s"
  upstream: "origin/stage/06-ebbo-design at P9b-start query; always re-run git branch -vv"
  upstream_distance: "run: git rev-list --left-right --count HEAD...@{upstream} only when an upstream exists"
  stage3_implementation_commit: 2ce66a4f66c0e446fa8b44a729783074cc13064a
  stage3_publication_commit: f6f3e1dd19427704971d443f28e894ce57af3676
  stage4_design_commit: cf1e06b5fcaac29a4c17694e2f1f336e784a9521
  stage4_design_committed_locally: true
  stage4_design_pushed: true
  stage4_p3a_commit: a0b24b118870633855f14553e06c0989c92a3aac
  stage4_p3a_committed_locally: true
  stage4_p3a_remote_status: published
  stage4_p3a_status_commit: 3cca849
  stage4_p3b_commit: 576b1dd7d39e9f4c5ecd79bc771a23dfaa539852
  stage4_p3b_committed_locally: true
  stage4_p3b_remote_status: published
  stage4_p3b_status_commit: 51b8d44
  stage4_p4_commit: c7a1ae4c151125c4f3e45185ce62403a92942883
  stage4_p4_status_commit: 59c335757b65935b29b7141ef6f0e6d338eb3603
  stage4_runtime_published: true
  stage5_p5_implementation_commit: 38428700d8f272f8107e8cd042f5fdec24d3e33d
  stage5_p5_status: "implemented by the commit above; query current HEAD, upstream, and publication with live Git"
  stage5_p6_local_baseline: 7969b0d
  stage5_p6_implementation_commit: a94ce0c
  stage5_p6_status_commit: 7302ddd
  stage5_p6_status: "offline TSP protocol/dry-run only; P7a-start query found both P6 commits local-only and no upstream; query live Git"
  stage5_p7a_design_commit: 1953fc7
  stage5_p7a_status: "committed locally at P7b-0 start with no upstream; query publication status with live Git; documentation only"
  stage5_complete: false
  stage6_baseline: 08712c5a065818889b1b11b315dadafee9437d06
  stage6_p8_design_commit: 6efec474d091bebeadec8574d1c32aa1f8c22f2e
  stage6_p8_status: "published"
  stage6_p9a_commit: 4189f65970feab0a17299445641916c6245de4a8
  stage6_p9a_status: "published; deterministic serial offline engineering Mock"
  stage6_p9b_status: "published as fa3b464609354cd24b124c08a5522ef049537817; ancestor of published P9c commit"
  stage6_p9c_status: "published as b698649cdf360d56eb063fc257a0e6614a53b733; offline Mock acceptance passed; real async and P10 absent"
  stage6_runtime_implemented: "P9a serial Mock, P9b restricted-role Mock, and opt-in P9c single-process fake-async Mock only; real experiments absent"
  stage6_p9c_validation:
    pytest: "221 passed, 1 skipped; completed before final documentation-only update"
    ruff_check: "passed: src tests"
    ruff_format_check: "74 files already formatted"
    mypy: "Success: no issues found in 44 source files"
    doctor: "stage6-p9c-ebbo-fake-async-mock-offline; default_provider=mock; network=unused"
    smokes: "Stage 2 12/12; Stage 3 18/13; Stage 4 44/28; P9a 5/5; P9b four paths unchanged; P9c 5 calls, 3 success, 2 failure, checksum 085fac4aa00ca567f055ab87b87084c896cfd463d5eb7a51741ccbae84e0e47f"
    git_diff_check: passed
    scope: "offline Mock control flow and replay only, not real async or E4 performance evidence"
  stage6_real_oracle_authorized: false
  agents_md_present: false
  codegraph_present: false
  network_required: false
  real_llm_enabled: false
  current_provider: mock-default
  openai_compatible_adapter: fake-transport-only
  http_transport_implemented: false
  environment_credentials_supported: false
  current_benchmark: deterministic TSP smoke plus FSU MKP protocol-only offline integration
  python_target: "3.11"
  validation_environment: roco-dev
  stage3_validation:
    pytest: "65 passed"
    ruff_check: passed
    ruff_format_check: passed
    mypy: "21 source files, no issues"
    doctor: "stage3-roco-ready"
    stage2_smoke: "12 llm_calls, 12 valid_evals, budget_reached=false"
    stage3_smoke: "18 llm_calls, 13 valid_evals, budget_reached=false"
    git_diff_check: passed
  stage4_p3b_validation:
    pytest: "75 passed"
    ruff_check: passed
    ruff_format_check: "36 files already formatted"
    mypy: "22 source files, no issues"
    doctor: "stage3-roco-ready; provider=mock; network=unused"
    stage2_smoke: "12 llm_calls, 12 valid_evals, budget_reached=false"
    stage3_smoke: "18 llm_calls, 13 valid_evals, budget_reached=false"
    stage4_memory_smoke: "44 llm_calls, 28 valid_evals, budget_reached=false"
    git_diff_check: passed
  stage4_p4_published_validation:
    pytest: "80 passed"
    ruff_check: passed
    ruff_format_check: passed
    mypy: "22 source files, no issues"
    doctor: "stage3-roco-ready; provider=mock; network=unused"
    stage2_smoke: "12 llm_calls, 12 valid_evals, budget_reached=false"
    stage3_smoke: "18 llm_calls, 13 valid_evals, budget_reached=false"
    stage4_memory_smoke: "44 llm_calls, 28 valid_evals, budget_reached=false"
    recovery_equivalence: "full/resumed canonical events, summaries, checkpoints, commits and hashes equal"
    ablation: "memory off 32/22/22; memory on 44/28/28 (calls/generated/valid)"
    git_diff_check: passed
  p5_offline_adapter:
    scope: "EoH and generation-local RoCo only; Stage 4 memory remains Mock"
    transport: "injected fake transport only; no HTTP implementation"
    credentials: "not read from os.environ, .env, keyring, or real secret stores"
    verification: "offline fake-transport tests; final validation recorded below"
  p5_worktree_validation:
    pytest: "125 passed"
    ruff_check: passed
    ruff_format_check: "39 files already formatted"
    mypy: "Success: no issues found in 23 source files"
    doctor: "stage5-provider-adapter-offline; default_provider=mock; network=unused"
    stage2_smoke: "12 llm_calls, 12 valid_evals, budget_reached=false"
    stage3_smoke: "18 llm_calls, 13 valid_evals, budget_reached=false"
    stage4_memory_smoke: "44 llm_calls, 28 valid_evals, budget_reached=false"
    git_diff_check: passed
  p6_tsp_protocol:
    scope: "TSP-only deterministic Mock/fake dry-run; not paper data or numerical reproduction"
    data: "synthetic deterministic TSP-50/TSP-100/TSP-200 with train/test manifest and SHA-256 checksums"
    dry_run: "72 results: 6 instances x 2 prompt-visibility conditions x 3 fixed seeds x EoH/RoCo"
    hard_limits_per_run: "24 LLM calls; 120000 mock tokens; 24 generated candidates; 24 valid evaluations; USD 1; 120 seconds"
    actual_per_run: "EoH 8 calls/8 valid evaluations; RoCo 18 calls/13 valid evaluations"
    prompt_visibility: "white-box/black-box are metadata-only prompt visibility conditions, not expensive oracles"
    validation: "133 passed; Ruff check/format; mypy 25 source files; doctor; unchanged 12/12, 18/13, 44/28 smoke; git diff --check"
  p7a_multicop_design:
    scope: "candidate COP evidence registry, unified run-record contract, fair-comparison rules, and preregistered statistical plan"
    candidates: "TSP, MKP, OP, BPP, CVRP, unresolved GLS; synthetic P6 TSP and frozen FSU MKP now have separate offline protocols"
    evidence: "ADR-0007 E0-E4; P7b advances only the authorized FSU MKP snapshot from P7b-0 E2 to an E3 offline Mock protocol"
    statistics: "future E4 cells require >=10 matched seeds, descriptive reporting, 10000 paired-bootstrap 95% interval, and explicit failed-run accounting"
    next: "G-041/E4, another COP, another download, or real provider work all require separate explicit authorization"
  p7b0_mkp_data_freeze:
    dataset: "John Burkardt/Florida State University KNAPSACK_MULTIPLE"
    local_version: "mkp-fsu-knapsack-multiple-v1; upstream has no release identifier and says last revised 2009-12-08"
    license: "GNU LGPL v3; verified from the source page and linked license text"
    inventory: "P01-P06: 18 required numeric input files plus optional P01/P05/P06 reference files; 21 files, 495 bytes"
    storage: "data/raw/mkp/fsu-knapsack-multiple/; ignored by Git; repository records provenance/checksums only"
    evidence_level: "E2 data source/inventory only; not E3, implemented, supported, reproduced, or evaluated"
    gaps: "G-037 source/license and G-038 inventory/checksum partially closed for this snapshot; split and G-039/G-040/G-041 remain open"
    network_boundary: "one explicitly authorized HTTPS source only; no LLM API, credentials, paid request, mirror, or runtime network"
  p7b_mkp_offline_protocol:
    protocol: "mkp-fsu-protocol-v1; P01-P06 all protocol-only, with no train/validation/test"
    parser: "explicit data root; frozen raw byte/count/SHA contract; unknown/missing/empty/malformed/inconsistent/negative inputs fail closed"
    evaluator: "list of item-index lists; one bag per item; hard capacities; raw_profit; only selection score=-raw_profit; spawned timeout"
    visibility: "single full_instance contract; optional reference and claimed optimum excluded; not a white/black or oracle comparison"
    budget: "mkp-fsu-mock-engineering-v1: 20 calls, 50000 tokens, 16 candidates, 16 valid evals, USD 0.25, 60 seconds"
    matrix: "root seed 707; P01-P06 x EoH/RoCo = 12 runs; EoH actual 8/8, RoCo actual 18/13 calls/valid"
    artifacts: "dataset manifest, P7a-shaped JSONL/CSV, six ledgers, raw/normalized audit values, non-time replay checksum; no summary statistics"
    evidence_level: "E3 for this exact offline Mock protocol only; commit and publication status require live Git"
    gaps: "FSU MKP subitems G-038/G-039/G-040 closed; G-041, E4, reference optimality, other COPs and paper reproduction remain open"
    safety: "network=unused; no real API/provider/key/cost; no memory runtime"
    validation: "151 passed; Ruff check and 52-file format check; mypy 30 source files; doctor; unchanged 12/12, 18/13, 44/28 smokes; 12-run MKP CLI/replay; git diff --check"
```

重要：Stage 4 设计已由 `cf1e06b` 冻结并发布，P3a/P3b 分别由 `a0b24b1` 与 `576b1dd`
发布。P4 恢复/消融实现由 `c7a1ae4c151125c4f3e45185ce62403a92942883` 固化，并由
`59c335757b65935b29b7141ef6f0e6d338eb3603` 记录完成和发布状态；Stage 5 分支以该提交为
精确基线。P5 离线 adapter 子任务由
`38428700d8f272f8107e8cd042f5fdec24d3e33d` 实现，但只以依赖注入的 fake transport
验证 EoH/RoCo 协议。仓库没有 HTTP transport、真实 endpoint/key、真实模型调用或付费
实验；这不等于整个 Stage 5、真实 provider 互操作或论文数值复现完成。

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
      |
  3cca849  docs: record Stage 4 P3a publication status
      |
  576b1dd  feat: add Stage 4 P3b memory runtime
      |
  51b8d44  docs: record Stage 4 P3b verification status
      |
  c7a1ae4  feat: add Stage 4 P4 deterministic recovery
      |
  59c3357  docs: record Stage 4 P4 completion status
      |
  3842870  feat: add offline OpenAI-compatible provider adapter
      |
stage/05-provider-adapter (query upstream and publication with live Git)
```

`stage/02-eoh-mvp` 还在另一个 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo
```

Stage 3 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage3
```

Stage 4 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage4
```

P6/P7 所在的历史 Stage 5 worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage5-protocol
```

P8 所在的当前 Stage 6 design worktree：

```text
/home/fj/RoCo-BO/RoCo-ebbo-stage6
```

该 worktree 的分支是 `stage/06-ebbo-design`，P8 基线是已发布的
`08712c5a065818889b1b11b315dadafee9437d06`，P8 设计由 `6efec47` 发布。P9a 开始时分支跟踪
`origin/stage/06-ebbo-design` 且 ahead/behind 为 0/0；P9a 后由 `4189f65970feab0a17299445641916c6245de4a8`
发布。P9b `fa3b464609354cd24b124c08a5522ef049537817` 是 P9c 的祖先；P9c 已由
`b698649cdf360d56eb063fc257a0e6614a53b733` 发布。此发布状态来自 P9c 提交的只读远端
分支核验记录；本次文档更新未重复联网核验。

`stage/04-reflection-memory` 已通过 `59c3357` 发布完整 Stage 4 V1。P6 本地基线为 P5
状态提交 `7969b0d`，实现/状态提交为 `a94ce0c`/`7302ddd`；P7a 是已设计的文档子任务，
其提交与发布状态须实时查询。P7a 开始时实时查询发现没有 upstream，故 P6 仍是本地提交；当前分支、HEAD、upstream
与发布状态必须用实时 Git 判断。不要在文档中固定自引用的 current HEAD 或 ahead/behind；用
`git rev-parse HEAD`、`git log -1 --format=%s`、`git branch -vv` 和适用时的
`git rev-list --left-right --count HEAD...@{upstream}` 获取实时值。实时 `git status`
显示的任何修改都属于当前工作，未经用户确认不得覆盖、丢弃、暂存或提交。

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
| Stage 4：反思与跨代记忆 | 已由 `59c3357` 发布 | ADR-0004、事实/恢复底座、opt-in 摘要/检索/截断/mutation、显式 resume 与离线消融 | 冻结 V1 离线 Mock 实现 100% |
| Stage 5：论文实验对齐 | P5/P6/P7a 有本地提交；P7b-0/P7b 与 upstream 状态须实时查询 | P6 合成 TSP Mock dry-run；P7a 证据协议；P7b 为 FSU MKP 提供 `protocol-only` E3 离线 Mock 协议 | P5/P6/P7a 和该 MKP E3 子范围完成；真实实验/论文对齐仍未完成 |
| Stage 6：多智能体 EBBO | P8/P9a/P9b/P9c 已发布；P9c 仅完成离线 Mock 验收 | P9a 串行 Mock；P9b 受限四角色；P9c 可选 fake-async pending/取消/恢复 Mock | P8/P9a/P9b/P9c 限定工程范围完成；真实异步与 P10 未开始 |

以“六阶段是否具有可运行实现”粗略计数，仍只完成前四阶段的既定 V1 范围，约为 4/6。
P5 完成 provider 协议与离线安全底座，P6 完成 TSP-only 合成协议和 Mock/fake dry-run，P7a
完成多 COP/统计证据设计，P7b-0/P7b 将获授权的 FSU MKP snapshot 从 E2 冻结推进到窄范围 E3
parser/evaluator/Mock dry-run。它们都不是论文数值复现、真实模型实验或统计结果；Stage 6 的 P8
设计、P9a 串行 Mock、P9b 受限角色 Mock 和 P9c fake-async Mock 只验证接口/账本/权限/恢复，
Stage 5–6 的真实实验与多智能体方法研究仍明显更重。

另一个必须说明的口径：相对于早期 roadmap 中更宽的 Stage 3 清单，当前约完成 70%–80%。roadmap 还提到 prompt 外置为 Jinja/YAML、上下文截断、修复重试、`no-critic`/`no-integrator` 消融和真实小预算运行；这些不在最近一次明确 Stage 3 任务范围内，且真实 API 被明确禁止，因此不是当前验收失败，而是后续候选任务。

## 6. 已实现架构与已冻结设计

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

### 6.6 Stage 5 P5：离线 OpenAI-compatible adapter

- `src/roco_ebbo/llm/openai_compatible.py`：EoH 与 generation-local RoCo adapter、严格
  请求/响应 schema、错误分类、版本化价格和脱敏 attempt audit。
- `OpenAICompatibleTransport` 与 `TokenCounter` 都由调用者显式注入；仓库不提供 HTTP
  transport，不读取 `os.environ`、`.env`、keyring、endpoint 或真实 key。
- 每次 transport attempt 都有显式 timeout 和有限 `max_retries`；只有 timeout、
  retryable transport、rate limit 和明确的 HTTP 5xx 可以在预算允许且 usage 结算完整时
  重试，不做内容修复请求。
- transport 已接受的 attempt 无论随后成功或失败都计一次 LLM call；有合法 usage 时按
  input/output tokens 和版本化价格表结算，缺失/非法 usage、解析失败和超预算均 fail closed。
- 请求、响应和 provider request ID 只以 hash 进入审计；固定安全错误不回显上游正文或
  认证信息。真实模型路径要求模型匹配的版本化 token counter，字符数不能冒充 token。
- Mock 仍是所有 CLI/smoke 默认 provider；adapter 只通过 fake transport、fake token
  counter 和 synthetic price table 离线验证。它不实现 `MemoryLLMProvider`，Stage 4
  memory runtime 继续使用 Mock。

详细边界见 `docs/adrs/0005-offline-openai-compatible-adapter.md`。这里的“完成”只指 P5
离线 adapter 子任务，不包括具体 HTTP/TLS/auth transport、真实 endpoint、真实 tokenizer/
价格核验、provider smoke、模型质量或论文实验。

### 6.7 Stage 5 P6：TSP-only 协议与离线 dry-run

- `a94ce0c` 在 P5 状态基线 `7969b0d` 上提供合成确定性 TSP-50、TSP-100、TSP-200；每个
  train/test 实例的坐标规则、seed、规模、split 和 SHA-256 都写入可重放 manifest。
- 默认矩阵产生 72 条结果（6 个实例 × white-box/black-box × 3 个固定 seed × EoH/RoCo）。
  这两个标签只表达 prompt visibility；它们不是昂贵 oracle，首次 Mock/fake 验证不主张效果差异。
- 公平性由每个 run 的相同硬上限定义：24 calls、120000 mock input/output tokens、24 generated
  candidates、24 valid evaluations、USD 1 和 120 seconds，而不是仅比较偶然的实际消耗。默认实际
  消耗为 EoH 8 calls/8 valid evaluations、RoCo 18 calls/13 valid evaluations。
- JSONL/CSV 工件记录 seed、split、instance checksum、method、provider、visibility、calls、tokens、
  cost、valid evaluations、candidates、wall time、best score 与失败/预算状态，并按 method/seed/split
  聚合；不计算或宣称统计显著性。完整边界见 ADR-0006 与 `paper_spec/tsp_experiment_protocol.md`。
- 133 tests、Ruff check/format、mypy（25 source files）、doctor、原有 12/12、18/13、44/28 三个
  smoke 和 `git diff --check` 已在完全离线路径通过。该验证不下载论文数据、不调用真实 API，
  也不构成模型性能结论或论文数值复现。

### 6.8 Stage 5 P7a：多 COP/统计与证据设计（已设计；提交/发布状态实时查询）

- ADR-0007 和 `paper_spec/multicop_experiment_protocol.md` 只登记 TSP、MKP、OP、BPP、CVRP 与
  未释义的 GLS 候选。除 P6 合成 TSP 外，任何候选均未支持、下载、适配、运行或复现。
- E0–E4 证据等级把候选名称、获授权来源/许可证、已验证离线 inventory/evaluator 和受授权真实实验
  分开；没有 E4 工件时禁止性能、显著性、泛化、优越性或论文数值复现结论。
- P7a 冻结跨 COP run record、六维硬预算、split 隔离、visibility、seed/provider-version 和失败/replay
  字段；P6 的 3-seed Mock/24-call profile 仅限 P6，不是多 COP 或真实实验默认值。
- 未来 E4 分析每个可比较 cell 至少 10 个匹配 seeds，报告描述统计、10,000 次 paired-bootstrap 95%
  interval 和所有失败；不使用 p-value/“显著”措辞，不跨 COP 聚合 raw score。P7b 之前须关闭
  G-037–G-041 的来源/许可证、inventory/checksum/split、evaluator 与预注册证据。

### 6.9 Stage 5 P7b-0：FSU MKP 数据来源冻结（E2 only）

- 用户只授权 John Burkardt/Florida State University 的 `KNAPSACK_MULTIPLE` HTTPS 来源；P7b-0
  下载并验证 P01–P06 的 18 个输入文件，以及源站存在的 P01/P05/P06 三个可选 reference。
- `docs/data_provenance/mkp_fsu_knapsack_multiple_v1.md` 记录来源/说明/许可 URL、2026-09-21 获取日期、
  上游 2009-12-08 修订说明、每个文件的 URL、字节数和 SHA-256。LGPL 链接核实为 v3。
- 21 个原始文件共 495 字节，均为非空纯文本数值文件；保存在 Git 忽略的
  `data/raw/mkp/fsu-knapsack-multiple/`，版本库不保存原始数据或 reference。
- 该冻结只为 MKP 部分关闭 G-037 的来源/许可和 G-038 的 inventory/checksum；未定义 split，
  G-039 evaluator、G-040 实验账本/provider 与 G-041 统计仍开放。MKP 仍不是 E3、已实现、已支持或已复现。

### 6.10 Stage 5 P7b：FSU MKP E3 离线 Mock 协议（已验证；提交/发布状态实时查询）

- `src/roco_ebbo/benchmarks/mkp.py` 只从调用者显式 data root 加载 P01--P06；逐文件验证 P7b-0
  byte count/SHA-256，拒绝未知/缺失/symlink/空/非整数/超范围/长度不一致/负 capacity 或 weight。
- `mkp-fsu-protocol-only-v1` 将六个极小实例全部标为 `protocol-only` integration split；没有
  train/validation/test、参数/模型选择、训练或统计。这是防止把小型适配样本冒充正式实验集。
- `mkp-fsu-evaluator-v1` 在 spawned subprocess 中执行
  `heuristic(capacities, weights, profits) -> list[list[int]]`；重复物品、非法索引和超容量均无效。
  来源目标是 maximize `raw_profit`，现有统一 Top-N 唯一选择分数仍为 minimize `-raw_profit`；
  normalized score 只审计，不用于选择或 optimality gap。
- 唯一 `full_instance` visibility 包含 capacity/weight/profit/目标/约束/签名，明确排除 optional
  reference 与 claimed optimum；它不是 white/black 对比或昂贵 oracle。reference 不进入 prompt/打分，
  也不被假定为已验证最优解。
- `mkp-fsu-mock-engineering-v1` 的每 run 相同 ceiling 为 20 calls、50000 Mock tokens、16 candidates、
  16 valid evals、USD 0.25、60 seconds。固定 root seed 707 的 P01--P06 × EoH/RoCo 共 12 run；
  实际 EoH 为 8 calls/8 valid，RoCo 为 18/13，provider 固定 Mock、`network=unused`，memory 未接入。
- 工件只有 dataset manifest、P7a-shaped JSONL/CSV、六类 ledger、raw/normalized audit 值和忽略
  wall time 的 replay checksum；不生成统计 summary、interval、排名、性能或跨 COP 结论。
- 这只关闭 FSU MKP 的 G-038/G-039/G-040 E3 子项。G-041、E4/真实 provider、reference 最优性、
  其他 COP 与论文数值复现仍开放；实现和发布状态一律实时 Git 查询。

### 6.11 Stage 6 P8/P9a/P9b/P9c：P9b/P9c 已发布；P9c 离线 Mock 完整验收通过

- ADR-0008 区分昂贵 oracle black-box 与论文 prompt visibility，并冻结单目标 minimize、可选
  `g_i(x)<=0` 约束、失败/超时/噪声/成本和预算边界。
- `paper_spec/ebbo_design.md` 定义 JSON-safe `OracleRequest`、`OracleResult`、`Observation`、
  `EvaluationStatus`，以及 accepted attempt 必计 `oracle_calls` 的审计状态机。
- EBBO ledger 将 oracle calls、成功/失败 evaluations、candidate proposals、LLM calls/tokens、按
  source+unit 的 cost 和 wall-clock 分账；它是新概念契约，不修改 Stage 2--5 `BudgetLedger`。
- 模块边界为 oracle adapter、observation store、surrogate、acquisition、finite candidate pool、
  scheduler、role controller 和 artifact/reporting；P9a 首先只做串行 deterministic Mock。
- 角色重定义为 global explorer、local exploiter、model critic、resource integrator。Integrator 只能
  从统计 candidate pool 选择，scheduler 是唯一 oracle dispatch capability。
- 评测设计冻结同 surrogate/同 oracle budget 的单 agent acquisition baseline、多 agent 对照、simple
  regret/cost/failure/time 指标和消融矩阵，但 EI/UCB/TS、surrogate、benchmark 和统计值都仍未选择。
- P9a 在独立 `src/roco_ebbo/ebbo/` 中实现 strict JSON、canonical SHA-256 ID/63-bit seed、
  `ebbo-ledger-v1`、append-only audit/Observation store、工程 Mock oracle、finite immutable pool 和
  scheduler-only `max_concurrency=1` dispatch；旧 `BudgetLedger` 未修改。
- 工程 surrogate 为 nearest successful Observation mean + normalized integer distance uncertainty；
  acquisition 为 minimization LCB `mean-beta*uncertainty`，score 后按完整 candidate ID tie-break。它们
  stdlib-only、确定性且透明，但不是论文事实、概率校准或性能已验证 BO 方法。
- 固定 smoke 是 `x in [-5,5]`、`(x-2)^2+1`、constraints off、noise none、root seed 9061、beta 2、
  pool 4。精确账本为 5 calls、5 success/0 failure、20 proposals、5 mock-evaluation-unit、0 LLM/
  tokens/财务成本、`network=unused`。
- P9a 已由 `4189f65970feab0a17299445641916c6245de4a8` 发布。P9b 新增独立版本化角色
  request/response、fake provider、结构化角色审计、advisory/hard critic veto 和 fail-closed 降级；
  角色只读同一 observation/pool view，Integrator 只能选池内 ID；受限 scheduler 在旧 serial
  dispatch 前再校验 pool、domain/constraint、duplicate 和预算。
- P9b 四路径 full/no_roles/no_critic/no_integrator 使用相同 Mock 与 root seed，分别为 20/0/15/15
  次 fake role calls；每路径均为 5 oracle calls、5 success、20 proposals、5 Mock cost、0 财务成本、
  `network=unused`。no_roles 的 replay checksum 保持 P9a 原值。P9b 已由 `fa3b464` 发布。
- P9c 仅新增 opt-in 单进程 deterministic fake-async Mock：`max_concurrency=2` 的 pending
  reservation/expected-cost hold、取消确认、乱序完成、独立 async ledger 和 commit-last checkpoint。
  smoke 为 5 calls、3 success/2 failure、20 proposals、5 synthetic Mock cost、0 LLM/tokens、
  `network=unused`，中断恢复与不中断的非时间 replay checksum 同为
  `085fac4aa00ca567f055ab87b87084c896cfd463d5eb7a51741ccbae84e0e47f`。P9c 已由
  `b698649cdf360d56eb063fc257a0e6614a53b733` 发布。
- P9c 本地完整门禁：221 passed/1 skipped；Ruff check/format、mypy（44 source files）、doctor、
  Stage 2/3/4 与 P9a/P9b/P9c 六条离线 CLI smoke、`git diff --check` 均通过。仅表示工程 Mock 验收。
- G-042 已关闭；G-043/G-044 的 P9b 共享读取/池内选择子项、G-051 的角色权限/降级/四路径子项
  已关闭。G-048/G-052 的 P9c Mock pending/recovery 子项已关闭；真实异步、G-049 成本感知
  acquisition、G-050 统计与 G-051 memory 仍开放。
  没有 E4 工件不得作 EBBO 性能或优越性结论。P10 的离线待决字段与授权闸门见
  `docs/paper_spec/p10_experiment_preregistration_template.md`；模板不授权真实实验。

仓库仍没有 GP/神经 surrogate、概率 BO、EBBO memory、async worker、真实 EBBO benchmark、
真实昂贵 oracle、真实 LLM 调用、网络调用或付费实验。

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

### 7.2 Stage 3 剩余非阻断风险

提交前加固已经覆盖 provider 异常、Integrator 失败、timeout、默认 T=3、多代 trace、
两类预算中断、非有限配置和最小化契约。剩余项属于后续耐久性或真实 provider 范围：

1. 决定 trace 是否需要逐代立即落盘/原子写。目前 CLI 在 engine 完整返回后统一写文件；正常运行满足每代可序列化 trace，但进程崩溃时没有逐代耐久性。
2. P5 adapter 已用 fake transport 固化“accepted attempt 必计 call、usage 缺失 fail closed”的
   离线规则；具体网络 SDK、远端服务和真实账单是否符合该规则仍未验证。
3. 最大化任务尚不支持；进入实现前需要版本化 objective contract，并同步 prompt、Mock Critic、排序和测试。

### 7.3 roadmap 与当前实现的差异

以下差异已经知道，不应由新 AI 误判为隐蔽完成：

- roadmap 建议 Jinja/YAML prompt；当前用版本化 Python 常量。
- roadmap 曾建议 `Proposal/Critique/Revision/IntegrationDecision` 多 schema；当前使用统一 `RoleRequest/RoleResponse`。
- roadmap 提到相邻 `+1/+2`；当前可执行规格与实现使用边界安全的相邻 `±1`，仍需 PDF 逐式复核。
- Stage 3 本身没有上下文截断、自动修复重试或 no-role 消融开关；P3b 只为 opt-in
  memory Mock 增加确定性字符截断，不把它冒充 tokenizer。
- 已有 OpenAI-compatible adapter 的离线协议实现，但没有 HTTP transport、真实 endpoint/
  key、真实 provider smoke 或付费请求；不得把 fake transport 测试称为真实互操作。
- P4 只提供显式目录的 Mock memory checkpoint resume 和提交后确定性中断，不做跨
  run 自动发现或任意进程点故障注入；缓存、并行调度和容器级沙箱也未实现。

修改这些行为前必须先更新 ADR/规格及预算公式，不能静默改变现有 smoke 回归。

## 8. 明确未实现的功能

### Stage 4

- 已完成并发布的设计：`roco-memory-event-v1`、角色摘要、minimize `delta_g`、K=5 的
  3/2 成败检索、每精英 E/X/I 三次 mutation、代级 segment/commit/checkpoint 与恢复不变量；
- 已提交、已验证的 P3a：严格 memory schema、Stage 3 trace 纯转换器、
  不可变 generation segment、commit-last 校验、checkpoint 序列化与恢复读取底座；
  代码提交为 `a0b24b1`，验证为 65 passed、Ruff check/format、mypy、doctor、Stage 2
  12/12 smoke、Stage 3 T=2 18/13 smoke 与 `git diff --check` 均通过；
- P3b 已由 `576b1dd` 发布：LTReflect/角色摘要运行时、K=5 检索、可审计 prompt 截断与
  memory-guided mutation 的显式 opt-in 接入；75 tests 与完整门禁通过；
- P4 已由实现提交 `c7a1ae4` 固化：显式 `resume_smoke`/`EoHEngine.resume`、只从
  连续有效 commit 恢复、config/seed/坏 hash/gap fail-closed、提交后中断、两路径规范工件
  与哈希等价、以及 memory-off/on 的 32/22/22 对 44/28/28 消融记账；80 tests 与完整门禁
  通过，并由状态提交 `59c3357` 发布。Stage 4 冻结 V1 的离线 Mock 实现已完成。

### Stage 5

P5 已完成无 HTTP 实现的 OpenAI-compatible EoH/RoCo adapter，以及 fake transport、
fake token counter 和 synthetic price table 的离线验证；这只是 Stage 5 基础设施子任务。
P6 已完成合成确定性 TSP-50/100/200 的 checksum/train-test 协议和 72 条 Mock/fake dry-run，
但不是论文原始数据或数值复现。以下登记的证据缺口仍未解决：G-012、G-016、G-021、G-034、
G-035、G-036。P7b-0/P7b 只把获授权的 FSU MKP snapshot 推进到 `protocol-only` E3，关闭该
snapshot 的 G-037–G-040 子项；G-041 和任何 E4/正式实验仍未关闭。
以下内容仍未实现：

- 具体 HTTP/TLS/auth transport、真实 endpoint/key 注入、真实 provider 兼容性
  smoke、模型 tokenizer/价格核验或任何付费调用；
- 论文原始 TSP 数据、实例数量、prompt、timeout、预算和 white-box/black-box 精确证据；
- 非 Mock 的实际方法比较、真实模型成本/Tokenizer 核验与受授权的真实实验；
- MKP 的正式 train/validation/test、reference 最优性、真实 provider/E4 与统计；OP、BPP、CVRP 和
  GLS 连获授权数据来源也没有；
- 受授权真实实验、预注册统计执行、置信区间/结果报告和论文数值报告。

### Stage 6

P8 已完成文档设计；P9a 已发布 deterministic Mock oracle、strict contracts、独立 ledger/store、
finite pool、serial scheduler 和 nearest-observation/LCB 工程 baseline。P9b 已由 `fa3b464`
发布四角色受限 Mock；P9c 已由 `b698649` 发布 opt-in fake-async pending/取消/恢复 Mock。
以下能力仍未实现：

- 任何真实昂贵 oracle adapter、真实 benchmark 或网络 transport；
- GP/神经/概率 surrogate、校准、EI/TS 和 acquisition 比较；
- 真实异步 worker/远端 reconciliation、任意指令点 crash 恢复及真实成本感知 acquisition；
- memory 接入、regret/target/statistical experiment 和 E4 工件。

## 9. 推荐后续任务顺序

```text
P0  Stage 3 最终审计/小范围加固（已完成）
  -> P1  Stage 3 提交并发布远端分支（已完成）
  -> P2  Stage 4 可执行规格和 ADR-0004（已完成、已提交并发布）
  -> P3a memory schema/trace 转换/segment store/commit-last/checkpoint 恢复底座（已发布）
  -> P3b 角色摘要/K=5 检索/可审计 prompt 截断/memory mutation 接入（已发布）
  -> P4  engine 级中断恢复、不中断/恢复端到端等价、memory/no-memory 消融（已发布）
  -> P5  OpenAI-compatible adapter，仅以 fake transport 离线验证（`3842870`；发布状态实时查询）
  -> P6  Stage 5 TSP 协议与 Mock/fake dry-run（`a94ce0c`；已实现，发布状态实时查询）
  -> P7a 多 COP/统计协议与证据设计（已设计；提交/发布状态实时查询；不自动授权真实 API）
  -> P7b-0 获授权 FSU MKP 来源/许可/inventory/checksum 冻结（E2；实现/发布状态实时查询）
  -> P7b FSU MKP parser/evaluator/protocol-only split 与 Mock/fake dry-run（E3 已验证；提交/发布状态实时查询）
  -> 后续 Stage 5 实施（须另行授权具体 COP/E4 数据、provider 与预算；G-041 仍开放）
  -> P8  Stage 6 EBBO 设计规格（`6efec47` 已发布）
  -> P9a deterministic Mock expensive-oracle + Observation/ledger + 串行最小 baseline（`4189f65` 已发布）
  -> P9b 受限四角色控制层 + finite candidate-pool-only 调度（`fa3b464` 已发布）
  -> P9c opt-in fake-async pending/失败账本/取消与显式恢复（`b698649` 已发布；仅 Mock）
  -> P10 仅在明确授权 benchmark/source/license、真实 provider/oracle 和硬预算后开展实验
```

不要在后续返工中把 P3a、P3b、P5 和 P6 合成一次任务：事实/恢复底座、运行时记忆、
provider 离线协议和论文实验协议应该分别审查。具体 HTTP transport、真实凭据、provider
smoke 和付费实验也不由 P5 或 P6 自动授权，必须另行明确批准和设置硬预算。P9a、P9b、P9c 不得
合并跳过：账本/oracle 底座、语言角色权限和异步恢复具有不同的失败与审计边界。

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

### 11.5 Prompt E：P5 离线 OpenAI-compatible adapter（已完成，保留作回归模板）

此子任务晚于 Mock + memory 路径稳定，只验证 adapter 边界，不授权真实网络或付费调用：

```text
为现有 LLMProvider/RoleLLMProvider 设计并实现 OpenAI-compatible adapter，但本任务不得实现或发起 HTTP/network transport，不得读取 os.environ、.env、keyring，不得读取或输出真实密钥，也不得产生费用。Stage 4 memory provider 继续使用 Mock。

使用显式依赖注入、fake transport、模型匹配的 fake token counter 和 synthetic 价格表测试：请求 schema、角色温度、timeout、重试上限、accepted-then-error 结算、JSON/schema、usage、token/费用记账、错误分类、版本、上下文决定和敏感字段脱敏。Mock 仍是默认 provider，CI 必须完全离线；仓库不提供可被默认或显式配置初始化的 HTTP 客户端。

新增 ADR 和无 endpoint/key 的独立示例配置，但 `.env`、真实响应与真实价格不得提交。保持所有现有 smoke 精确回归。离线通过不等于真实 provider 互操作、模型实验或论文复现。不要实际调用 API、不要 commit/push。
```

### 11.6 Prompt F：Stage 5 TSP 复现实验准备

```text
先做 Stage 5 的 TSP-only 实验协议与 evaluator 扩展，不接入 MKP/OP/BPP/CVRP，也不运行昂贵真实实验。

核验论文 TSP 数据规模、训练/测试实例数、white-box/black-box prompt、timeout 和预算证据；不能确认的值登记为缺口。实现数据 checksum、TSP-50/100/200 配置、训练/测试分离、聚合 schema、3-seed dry-run 和 EoH/RoCo 等预算比较接口。结果必须同时按 valid_evals、llm_calls、tokens 和 wall time 报告。

先用 Mock/fake provider 完成 dry-run；真实模型实验另行授权。不得把论文 black-box prompt 写成昂贵 oracle 黑盒，不实现 EBBO。保持 Stage 2/3/4 smoke 回归，不 commit/push。
```

### 11.7 Prompt G：Stage 6 EBBO 设计（P8 已完成，保留作设计审计模板）

```text
基于 `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md` 和现有 RoCo-AHD 结果，设计 Stage 6 的多智能体昂贵黑盒优化架构，但本任务不编码。

明确问题定义、oracle budget、噪声/失败/约束、共享 posterior、异步 pending points 和 wall-clock/cost；将角色重新定义为 global explorer、local exploiter、model critic、resource integrator。Integrator 只能在 surrogate/acquisition 产生的统计候选池中选择或调度，不能让自然语言判断直接消耗昂贵 oracle。

给出最小基线（同一待选择 surrogate 下的 EI/UCB/TS 候选）、多 agent 对照、固定 oracle 预算、公平指标、消融矩阵、模块接口、ADR 和分阶段实现提示词。不要声称 RoCo 论文已经证明 EBBO 有效，不实现真实实验或调用外部服务。
```

### 11.8 Prompt H：P9a 串行 Mock EBBO 底座（已完成，保留作实现审计模板）

```text
以 ADR-0008、paper_spec/ebbo_design.md、parameter_registry 和 G-042--G-050 为唯一 Stage 6
设计基线。先关闭 P9a 所需的 ledger/canonical JSON/seed、最小 surrogate/acquisition、Mock function/
search space 和串行失败语义子项，再实现 deterministic Mock expensive-oracle、OracleRequest/
OracleResult/Observation/EvaluationStatus、独立 observation store/EBBO ledger、finite candidate pool 和
max_concurrency=1 的单 agent BO baseline。

不得修改现有 BudgetLedger 语义；旧 Stage 2--5 smoke 和工件必须回归不变。accepted oracle attempt
即计 oracle_calls/cost；失败、timeout、取消、duplicate、非法结果和 cost overrun 都需结构化负路径。
不接四角色控制、memory、异步 worker、真实 benchmark/provider/API/key/network 或付费实验，不声称
性能。不得把 EI/UCB/TS、GP 或第三方库当作已决定项；先用 ADR/gap 关闭证据和依赖边界。
```

### 11.9 Prompt I：P9b 受限角色控制（已实现，保留作审计模板）

```text
以已验证的 P9a contracts/ledger/store/surrogate/acquisition/candidate pool/serial scheduler 为不可绕过
底座，实现 global explorer、local exploiter、model critic、resource integrator 的 JSON-safe 控制层。
角色只能解释已提交 Observation/posterior、提出区域/策略偏好、审查不确定性和引用 pool entry ID；
Integrator 不得构造池外候选或直接调用 oracle，scheduler 仍是唯一 dispatch capability。

保持相同 surrogate/acquisition、Mock oracle、root seed 和 oracle-call hard limit，增加完整角色、无角色、
无 critic、无 integrator 的控制流/权限测试。默认不接 memory，不实现 async/pending worker，不接真实
benchmark/provider/API/key/network，不运行性能实验，不修改 Stage 2--5 BudgetLedger 或 smoke。
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

P8 已在发布基线 `08712c5a065818889b1b11b315dadafee9437d06` 上完成并由 `6efec47` 发布 Stage 6 文档设计：
ADR-0008 和 `paper_spec/ebbo_design.md` 冻结 expensive-oracle 与 prompt black-box 的区别、JSON-safe
request/result/observation/status、独立 EBBO ledger、accepted-attempt 结算、稳定 ID/seed、模块数据流、
共享 posterior、有限 candidate pool、角色权限、pending/异步未来语义、评测/消融与 P9/P10 闸门。
P9a 已由 `4189f65970feab0a17299445641916c6245de4a8` 发布；P9b `fa3b464` 为已发布
P9c `b698649cdf360d56eb063fc257a0e6614a53b733` 的祖先。P9c 只通过离线 fake-async Mock
验收；HEAD、status、upstream 仍须实时查询，不能凭本地跟踪引用推断远端现状。

下一步使用 `docs/paper_spec/p10_experiment_preregistration_template.md` 登记仍为 `unset` 的决策；
真实异步/reconciliation 或 P10 实验均需要独立授权和协议。P10 必须重新取得用户对 benchmark、
来源、许可证、真实 oracle/provider、硬预算和统计计划的明确授权。

Stage 6 当前准确状态是“P8/P9a/P9b/P9c 已发布；P9c 仅通过 fake-async 工程 Mock 验收；
真实异步和 P10 未实现”。
没有 E4 工件，不得作性能、显著性、泛化、优越性或论文复现结论。
