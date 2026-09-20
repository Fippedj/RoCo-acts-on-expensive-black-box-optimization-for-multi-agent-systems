# RoCo-EBBO

Method-level reproduction of **RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design**, followed by a migration toward multi-agent expensive black-box optimization (EBBO).

This repository contains deterministic Stage 2/3 baselines and the Stage 4 V1 opt-in offline memory
path. P4 recovery and ablation were verified and formed local implementation commit `c7a1ae4`; use
live Git status to determine publication. It does **not** claim to be the authors' official
implementation or a completed paper reproduction; real-provider and paper experiments remain P5+.

## Recommended local setup

Develop in WSL2 Ubuntu 22.04+ (or native Linux), with the repository stored in the Linux filesystem:

```bash
git clone https://github.com/Fippedj/RoCo-acts-on-expensive-black-box-optimization-for-multi-agent-systems.git ~/projects/roco-ebbo
cd ~/projects/roco-ebbo
conda env create -f environment.yml
conda activate roco-dev
python -m pip install -e '.[dev,llm]'
pytest
python -m roco_ebbo doctor
python -m roco_ebbo smoke --config configs/smoke/tsp_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_roco_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_memory_mock.yaml
```

Open the folder from WSL with VS Code:

```bash
code .
```

Do not develop under `/mnt/c/...` for normal work; Linux-native paths have more reliable subprocess, permissions, and I/O behavior.

## Repository map

| Path | Purpose |
|---|---|
| `docs/START_HERE.md` | First-week implementation order and handoff instructions |
| `docs/AI_PROJECT_STATE_AND_PROMPT_GUIDE.md` | AI-readable repository state, audit findings, roadmap status, and reusable task prompts |
| `docs/adrs/0003-stage3-roco-collaboration.md` | Stage 3 state machine, failure, trace, and memory-boundary decisions |
| `docs/adrs/0004-stage4-reflection-memory-design.md` | Stage 4 memory, retrieval, truncation, commit, and recovery decisions |
| `docs/RoCo_reproduction_and_EBBO_roadmap.md` | Six-stage reproduction and migration plan |
| `docs/paper/` | Source-grounded reading notes and paper-gap analysis |
| `configs/paper_defaults.yaml` | Paper-aligned settings, annotated with non-disclosed items |
| `configs/smoke/tsp_mock.yaml` | Unchanged Stage 2 deterministic EoH regression configuration |
| `configs/smoke/tsp_roco_mock.yaml` | Deterministic Stage 3 four-role collaboration configuration |
| `configs/smoke/tsp_memory_mock.yaml` | Opt-in two-generation Stage 4 offline memory configuration |
| `src/roco_ebbo/` | RoCo / EBBO implementation package |
| `tests/` | Unit, integration, and regression tests |
| `scripts/` | WSL bootstrap and later experiment entry points |

## Reproducibility rules

- Never commit API keys, raw LLM conversations, downloaded datasets, or large experiment logs.
- Every real run must record git SHA, seed, prompt version, model, temperatures, budget ledger, dataset checksum, and environment export.
- Track `llm_calls`, `tokens`, `generated_candidates`, `valid_evals`, cost, and wall-clock time separately.
- CI uses only a mock LLM and small deterministic tests.

## Paper facts versus engineering decisions

The paper specifies GPT-4o-mini, population size `N=10`, collaboration rounds `T=3`, and role temperatures. It does not disclose OS, Python/dependency versions, hardware, long-term-memory retrieval, or full retry policies. The primary environment here is Linux/WSL2 + Conda + Python 3.11 as an engineering decision, not a claim about the authors' machine.

See `docs/START_HERE.md` before extending the current stage.

## Stage 2 deterministic baseline

The retained Stage 2 executable path is deliberately small and free of real API cost:

1. A seeded `MockLLMProvider` creates one structured candidate for each E1/E2/M1/M2 operator.
2. Candidate source is checked with a restrictive AST/function-signature allow-list.
3. `heuristic(distance_matrix) -> tour` executes only in a spawned subprocess with a per-candidate timeout.
4. Valid TSP-20 tours receive a closed-tour score; parents and children are merged and selected by deterministic Top-N.
5. The smoke preset initializes four candidates and runs two generations, for 12 mock calls and at most 12 valid evaluations.

Run manifests and JSONL event logs are written below the ignored `runs/` directory. The evaluator is only a development sandbox: it does not provide container, operating-system-user, syscall, filesystem, or network isolation and must not run untrusted code.

This legacy path remains selected by `evolution.mode: eoh` (also the default when `mode` is absent). Its Stage 2 candidate sequence, call count, and selection behavior are retained as a regression contract.

## Stage 3 deterministic RoCo collaboration

The independent `tsp_roco_mock.yaml` preset selects `evolution.mode: roco`. `EoHEngine` invokes an optional, generation-local `RoCoCollaborator` after producing the ordinary EoH offspring and before Top-N selection. For each generation it runs one auditable collaboration:

1. Seeded elite-pair sampling and an initial Critic comparison (`round=0`).
2. Exactly `T` Explorer/Exploiter proposal-and-evaluation rounds; the Critic separately compares each branch with its preceding valid version.
3. One final Integrator proposal and evaluation.
4. A unified deterministic Top-N over the valid evaluated population, EoH offspring, and collaboration candidates.

The role contracts are distinct even though the local preset shares one provider: Explorer favors novelty at temperature 1.3, Exploiter favors conservative refinement at 0.8, and Critic/Integrator use 1.0. The paper default is `T=3`; the smoke preset may use a smaller explicit value to keep tests cheap.

With its committed `N=4`, one generation, one E1/E2/M1/M2 child each, and `T=2`, the all-valid RoCo smoke makes 18 Mock calls and 13 valid evaluations: 8 EoH candidate calls plus 10 role calls, of which 5 produce collaboration candidates. This arithmetic is an engineering smoke expectation, not the paper's budget.

The Mock provider is role-aware, seeded, offline, and makes no network or credential access. Every candidate still passes the same AST/signature checks and spawned, timeout-bounded TSP evaluator. Invalid role output, invalid candidates, provider failures, and exhausted budgets become structured trace events; they do not invalidate already completed work.

Each RoCo run writes `collaboration_trace.jsonl` beneath its run directory, one JSON object per generation. It records the sampled pair, ranks and sampling power, requested/completed rounds, ordered role events, inputs and outputs, evaluation results, budget snapshots, failures, and selected candidate IDs. This is an execution trace only: Stage 3 does **not** implement LTReflect, cross-generation retrieval, memory-guided mutation, real model providers, paper-scale evaluators, or EBBO.

See `docs/adrs/0003-stage3-roco-collaboration.md` for the prompt contracts, failure degradation, and trace schema.

## Stage 4 V1 deterministic memory and recovery

Published P3b adds a separate `tsp_memory_mock.yaml` smoke preset. Memory remains explicitly opt-in:
the legacy Stage 2 and Stage 3 configs do not construct a memory runtime. The offline path summarizes
Explorer/Exploiter/Integrator facts, retrieves at most five prior committed role-scoped events with
a 3/2 balance, audits deterministic character truncation, and evaluates one memory-guided candidate
per role and configured elite before the existing unified Top-N.

For its fixed two generations, `T=2`, and `elite_count=1`, the all-valid Mock budget is 44 LLM calls
and 28 valid evaluations. Each completed generation is published through the P3a immutable segment,
summary, checkpoint, and commit-last store.

P4 exposes `run_smoke(...,
interrupt_after_committed_generation=1)` and `resume_smoke(...)`. Resume only examines the explicitly
named memory directory, rejects committed corruption, generation gaps, and config/seed mismatches,
and continues from the next engine generation without charging prior work again. A paired
`run_memory_ablation(...)` entry keeps the same seed and two-generation RoCo settings: memory-off is
32 calls / 22 generated candidates / 22 valid evaluations and writes no memory artifacts; memory-on
remains 44/28/28. These counts establish control-flow boundaries, not a performance comparison.

Stage 4 V1 does not add a real provider, network access, cache, embeddings, new benchmarks, EBBO, or
process-level crash orchestration outside the deterministic post-commit interruption control.

## Original repository purpose

把 RoCo 发展成多智能体昂贵黑盒优化方法
