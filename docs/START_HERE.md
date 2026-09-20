# Start here

## Development target

The current computer is for development and small tests only. Use WSL2/Linux, Conda, Python 3.11, a mock LLM, and TSP-20/TSP-50. Move larger API-budget experiments to the separate Linux machine after the deterministic path is tested.

## First-week order

1. Read `RoCo_reproduction_and_EBBO_roadmap.md` Stage 1 and `paper/RoCo_research_analysis.md`.
2. Create the environment and run `pytest` plus `python -m roco_ebbo doctor`.
3. Add the typed core models: `Candidate`, `EvaluationResult`, `Population`, `BudgetLedger`, and `RunManifest`.
4. Implement a deterministic TSP-20 evaluator with timeout, seed control, and a mock LLM provider.
5. Implement minimal EoH before implementing the four RoCo roles.

## VS Code + WSL

Install the VS Code **WSL**, **Python**, **Ruff**, and **YAML** extensions. From the Ubuntu terminal in repository root, run `code .`. Select the `roco-dev` interpreter when VS Code asks.

The committed `.vscode/` settings enable pytest discovery and Ruff formatting. They contain no machine-specific paths.

## Environment policy

- Main implementation: `roco-dev`, Python 3.11.
- Optional LLM4AD_Next adapter: a separate Python 3.12 environment only if needed.
- Optional legacy baseline environment: create `roco-baselines` only if ReEvo/EoH dependencies conflict.
- GPU is unnecessary for RoCo API-based small experiments. Add PyTorch/BoTorch later for the EBBO stage.

## Non-negotiable budget rule

The paper's body says 400 LLM calls per generation, while its appendix says a maximum of 400 evaluations. Treat these as distinct counters and always choose explicit hard limits in an experiment config.

## Current checkpoint and next task

The active Stage 4 worktree is `/home/fj/RoCo-BO/RoCo-ebbo-stage4` on
`stage/04-reflection-memory`. P2 design is published at `cf1e06b`; P3a is committed locally at
`a0b24b1` (`feat: add Stage 4 P3a memory foundation`), has passed 65 tests, Ruff, mypy, doctor,
and both existing smoke contracts, and is awaiting normal publication with its status document.
Use `git rev-parse HEAD` and `git rev-list --left-right --count HEAD...@{upstream}` for the live
commit and synchronization state instead of copying a fixed HEAD into documentation.

P3a supplies strict memory schemas, pure Stage 3 trace-to-event conversion, immutable generation
segments, SHA-256/commit-last publication, and JSON-safe checkpoint recovery. The next development
task is P3b: role-summary runtime calls, deterministic K=5 retrieval, auditable prompt truncation,
and memory-guided mutation. P4 still covers end-to-end recovery and ablation acceptance; Stage 4 is
not complete.

## Current Stage 3 executable scope

There are two deliberately separate offline smoke paths:

- `configs/smoke/tsp_mock.yaml` selects the legacy `evolution.mode: eoh` path. It keeps the Stage 2 contract: deterministic serial E1/E2/M1/M2 generation on one TSP-20 instance, with `collaboration_rounds` accepted but not executed. A missing `mode` also defaults to `eoh` for compatibility.
- `configs/smoke/tsp_roco_mock.yaml` selects `evolution.mode: roco`. Each generation samples one elite pair, runs the initial Critic, executes exactly the configured `T` Explorer/Exploiter rounds with a separate before/after Critic comparison for each branch, then evaluates one Integrator fusion candidate before unified Top-N selection. The paper default is `T=3`; this smoke preset uses `T=2` to remain cheap.

The role defaults are Explorer 1.3, Exploiter 0.8, Critic 1.0, and Integrator 1.0. All four roles use the seeded role-aware `MockLLMProvider`; neither smoke path calls a network API or reads credentials. The Mock path can replay candidate IDs, scores, role order, and non-time budget counters from the same config and seed.

Candidate code must define `heuristic(distance_matrix) -> tour`. EoH and RoCo candidates use the same AST/signature checks, spawned subprocess evaluator, per-candidate timeout, and run-scoped `BudgetLedger`. These controls are not a production security boundary; use the evaluator only with trusted local/mock code.

The RoCo path writes `collaboration_trace.jsonl` in the run directory, one serializable trace per generation. Check it for the elite pair, ranks, requested/completed rounds, role inputs and outputs, evaluation results, budget deltas, structured failures, and selected IDs. A failed role or invalid candidate is skipped safely; a hard budget stops new work without discarding already valid candidates.

This trace is short-lived run evidence. Stage 3 does not implement LTReflect, cross-generation memory storage/retrieval, or memory-guided mutation; those remain Stage 4 runtime work. Their design is now frozen in `adrs/0004-stage4-reflection-memory-design.md` and `paper_spec/memory.md`; do not treat those documents as an implemented feature. Real providers, expensive black-box optimization, and other benchmarks also remain out of scope.

```bash
conda activate roco-dev
python -m pytest
ruff check src tests
ruff format --check src tests
python -m roco_ebbo doctor
python -m roco_ebbo smoke --config configs/smoke/tsp_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_roco_mock.yaml
git diff --check
```

The complete Stage 3 protocol and failure semantics are in `adrs/0003-stage3-roco-collaboration.md`. Read `paper_spec/algorithm.md` alongside it. Before P3b, read `adrs/0004-stage4-reflection-memory-design.md` and `paper_spec/memory.md`; P3a has implemented their facts/recovery foundation, while P3b must add only the deferred summary, retrieval, truncation, and mutation runtime path.
