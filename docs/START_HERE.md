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

The active Stage 5 P6 worktree is `/home/fj/RoCo-BO/RoCo-ebbo-stage5-protocol` on
`stage/05-tsp-protocol`, based exactly on local P5 status commit `7969b0d`.
Use `git rev-parse HEAD` and live status commands for the current implementation state instead of
copying a self-referential Stage 5 HEAD into documentation.

P3a supplies strict memory schemas, pure Stage 3 trace-to-event conversion, immutable generation
segments, SHA-256/commit-last publication, and JSON-safe checkpoint recovery. P3b adds opt-in role-summary calls,
deterministic K=5 retrieval, auditable character-budget truncation, and three-role memory mutation.
It passed 75 tests, Ruff, mypy, doctor, the unchanged 12/12 and 18/13 smokes, and its new 44/28 smoke.
P4 was implemented by `c7a1ae4` and is included in the published Stage 4 checkpoint: it adds explicit checkpoint
resume from a caller-specified run/memory directory, post-generation-commit deterministic
interruption, full-versus-resumed non-time state and canonical artifact/hash equivalence, and a
memory-off/on ablation entry. The frozen Stage 4 V1 offline Mock implementation is complete.
Stage 5 P5 is implemented by `38428700d8f272f8107e8cd042f5fdec24d3e33d`: it adds an
OpenAI-compatible EoH/RoCo adapter with transport, token-counter, pricing, strict response, retry,
budget, audit, and redaction contracts. It has been exercised only with injected fake transport; the
repository still has no HTTP transport, reads no real key, makes no network request, and performs no
real-provider smoke. Mock remains the default provider; query current HEAD, upstream, and publication
state with live Git commands.

P6 is implemented by `a94ce0c`: it adds a TSP-only, synthetic deterministic TSP-50/TSP-100/TSP-200
manifest with per-instance SHA-256 checksums and separated train/test splits, plus a 72-result Mock/fake
dry-run (6 instances × two prompt-visibility conditions × three fixed seeds × EoH/RoCo). Each run has
the same fixed hard limits (24 calls, 120000 mock input/output tokens, 24 generated candidates, 24 valid
evaluations, USD 1, and 120 seconds); actual default use is EoH 8 calls/8 valid evaluations and RoCo 18
calls/13 valid evaluations. White-box and black-box denote prompt visibility, not an expensive oracle.
P6 passed 133 tests, Ruff, mypy, doctor, all three existing offline smokes, and `git diff --check`. It
uses synthetic deterministic data—not the paper's raw data or a numerical reproduction—and leaves
G-012, G-016, G-021, and G-034 through G-036 unresolved. Stage 5 is not complete; the next task is P7a
multi-COP/statistical-protocol and evidence design. Use live Git queries for HEAD, upstream, and publication.

## Current Stage 3 executable scope

There are two deliberately separate offline smoke paths:

- `configs/smoke/tsp_mock.yaml` selects the legacy `evolution.mode: eoh` path. It keeps the Stage 2 contract: deterministic serial E1/E2/M1/M2 generation on one TSP-20 instance, with `collaboration_rounds` accepted but not executed. A missing `mode` also defaults to `eoh` for compatibility.
- `configs/smoke/tsp_roco_mock.yaml` selects `evolution.mode: roco`. Each generation samples one elite pair, runs the initial Critic, executes exactly the configured `T` Explorer/Exploiter rounds with a separate before/after Critic comparison for each branch, then evaluates one Integrator fusion candidate before unified Top-N selection. The paper default is `T=3`; this smoke preset uses `T=2` to remain cheap.

The role defaults are Explorer 1.3, Exploiter 0.8, Critic 1.0, and Integrator 1.0. All four roles use the seeded role-aware `MockLLMProvider`; neither smoke path calls a network API or reads credentials. The Mock path can replay candidate IDs, scores, role order, and non-time budget counters from the same config and seed.

Candidate code must define `heuristic(distance_matrix) -> tour`. EoH and RoCo candidates use the same AST/signature checks, spawned subprocess evaluator, per-candidate timeout, and run-scoped `BudgetLedger`. These controls are not a production security boundary; use the evaluator only with trusted local/mock code.

The RoCo path writes `collaboration_trace.jsonl` in the run directory, one serializable trace per generation. Check it for the elite pair, ranks, requested/completed rounds, role inputs and outputs, evaluation results, budget deltas, structured failures, and selected IDs. A failed role or invalid candidate is skipped safely; a hard budget stops new work without discarding already valid candidates.

This trace is short-lived run evidence. Stage 3 itself does not implement LTReflect, cross-generation memory storage/retrieval, or memory-guided mutation; Stage 4 V1 supplies those capabilities through a separate opt-in runtime. Their design is frozen in `adrs/0004-stage4-reflection-memory-design.md` and `paper_spec/memory.md`. A transport-neutral adapter now exists, but real provider transport/interoperability, expensive black-box optimization, and other benchmarks remain out of scope.

P3b adds `configs/smoke/tsp_memory_mock.yaml` as a separate, explicit opt-in.
With two generations, `T=2`, and one memory elite, its no-failure accounting is 44 Mock LLM calls
and 28 valid evaluations. It writes P3a generation segments/summaries/checkpoints/commit markers plus
a runtime audit for retrieval and truncation. The existing Stage 2 and Stage 3 presets do not enable
memory and retain their 12/12 and 18/13 contracts.

## Stage 5 provider safety boundary

- `src/roco_ebbo/llm/openai_compatible.py` has no endpoint, credential loader, HTTP client, or
  import/construction side effect. A caller must explicitly inject a transport and a model-specific,
  versioned token counter.
- `configs/providers/openai_compatible_fake.example.yaml` contains no key or endpoint and uses only a
  fake model plus synthetic pricing. It is documentation, not a runnable network smoke config.
- Existing smoke configs and a missing provider selection resolve to Mock. The smoke loader rejects
  `openai-compatible`, so the normal CLI cannot silently initialize a network path.
- Fake tests cover EoH/four-role requests, temperatures, strict JSON/schema, error categories,
  timeout/retry limits, accepted-error accounting, usage/cost, budget closure, token-context audit,
  and sensitive-data non-echo.
- This proves only the offline adapter contract. A real transport, credentials, actual endpoint,
  tokenizer/pricing verification, API call, or paid experiment requires separate authorization.

```bash
conda activate roco-dev
python -m pytest
ruff check src tests
ruff format --check src tests
python -m roco_ebbo doctor
python -m roco_ebbo smoke --config configs/smoke/tsp_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_roco_mock.yaml
python -m roco_ebbo smoke --config configs/smoke/tsp_memory_mock.yaml
git diff --check
```

The complete Stage 3 protocol and failure semantics are in `adrs/0003-stage3-roco-collaboration.md`. Read `paper_spec/algorithm.md` alongside it. Stage 4 is bounded by `adrs/0004-stage4-reflection-memory-design.md` and `paper_spec/memory.md`; P3a is the facts/recovery foundation, P3b adds summary/retrieval/truncation/mutation runtime behavior, and P4 adds engine resume equivalence and memory/no-memory ablation. Stage 4 V1 is complete. ADR-0005 defines the completed offline P5 adapter boundary; ADR-0006 and `paper_spec/tsp_experiment_protocol.md` define completed P6 offline TSP protocol/dry-run boundary. Neither authorizes real-provider interoperability, model experiments, paper-reproduction claims, or P7a implementation.
