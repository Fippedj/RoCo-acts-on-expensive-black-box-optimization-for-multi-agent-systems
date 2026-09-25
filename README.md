# RoCo-EBBO

Method-level reproduction of **RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design**, followed by a migration toward multi-agent expensive black-box optimization (EBBO).

This repository contains deterministic Stage 2/3 baselines, the published Stage 4 V1 opt-in offline
memory path, a Stage 5 TSP-only Mock dry-run, a P7a multi-COP/statistics design, one P7b FSU MKP
offline integration protocol, and the completed Stage 6 EBBO design specification. Stage 6 runtime
now includes published P9a serial, P9b restricted-role, and P9c deterministic fake-async engineering
Mock paths. P9c was published as `b698649cdf360d56eb063fc257a0e6614a53b733`;
real experiments have **not** started. The repository does **not**
claim to be the authors' official implementation or a completed paper reproduction. No HTTP transport,
real-provider interoperability run, statistical experiment, or paper experiment has been performed.
The only external COP snapshot is the narrowly authorized, Git-ignored FSU P01--P06 MKP data used by
the P7b offline integration protocol.

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
python -m roco_ebbo ebbo-smoke --config configs/smoke/ebbo_mock.yaml \
  --output-dir /tmp/roco-ebbo-p9a-smoke
python -m roco_ebbo ebbo-role-smoke --config configs/smoke/ebbo_role_mock.yaml \
  --output-dir /tmp/roco-ebbo-p9b-smoke
python -m roco_ebbo ebbo-async-smoke --config configs/smoke/ebbo_async_mock.yaml \
  --output-dir /tmp/roco-ebbo-p9c-smoke
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
| `docs/adrs/0005-offline-openai-compatible-adapter.md` | Stage 5 transport injection, strict response, retry, budget, and security decisions |
| `docs/adrs/0006-stage5-tsp-protocol-dry-run.md` | TSP-50/100/200 inventory, result schema, fair ceilings, and offline dry-run boundary |
| `docs/adrs/0007-stage5-multicop-statistics-evidence.md` | Candidate-COP evidence levels, statistics plan, and P7b implementation gates |
| `docs/adrs/0008-stage6-ebbo-design.md` | Stage 6 oracle, ledger, module, role-permission, scheduling, and implementation-boundary decisions |
| `docs/RoCo_reproduction_and_EBBO_roadmap.md` | Six-stage reproduction and migration plan |
| `docs/paper/` | Source-grounded reading notes and paper-gap analysis |
| `configs/paper_defaults.yaml` | Paper-aligned settings, annotated with non-disclosed items |
| `configs/smoke/tsp_mock.yaml` | Unchanged Stage 2 deterministic EoH regression configuration |
| `configs/smoke/tsp_roco_mock.yaml` | Deterministic Stage 3 four-role collaboration configuration |
| `configs/smoke/tsp_memory_mock.yaml` | Opt-in two-generation Stage 4 offline memory configuration |
| `configs/smoke/ebbo_mock.yaml` | P9a serial deterministic Mock expensive-oracle smoke; no network or LLM |
| `configs/smoke/ebbo_role_mock.yaml` | P9b full/no-role/no-critic/no-integrator offline role-control smoke |
| `configs/smoke/ebbo_async_mock.yaml` | Opt-in P9c deterministic fake-async engineering smoke |
| `configs/experiments/tsp_mock_dry_run.yaml` | Fixed three-seed TSP protocol dry-run; Mock only, not a paper experiment |
| `configs/experiments/mkp_fsu_mock_dry_run.yaml` | P01--P06 protocol-only MKP engineering dry-run; Mock/network-unused only |
| `docs/data_provenance/mkp_fsu_knapsack_multiple_v1.md` | Authorized FSU source/license, raw checksums, parser/evaluator/split and E3 boundary |
| `docs/paper_spec/multicop_experiment_protocol.md` | P7a candidate-COP registry, run-record contract, comparability, and preregistered analysis plan |
| `docs/paper_spec/ebbo_design.md` | JSON-safe EBBO contracts, data flow, pending semantics, evaluation plan, and P9 task split |
| `docs/paper_spec/p10_experiment_preregistration_template.md` | Offline P10 decisions, preregistration fields, and E2/E3/E4 gates; no experiment authorization |
| `configs/providers/openai_compatible_fake.example.yaml` | Documentation-only, no-key fake-transport adapter example |
| `src/roco_ebbo/llm/openai_compatible.py` | Transport-neutral EoH/RoCo adapter and audit contracts; no HTTP implementation |
| `src/roco_ebbo/ebbo/` | Independent P9a foundation, P9b roles, and opt-in P9c fake-async ledger/scheduler/recovery |
| `src/roco_ebbo/` | RoCo / EBBO implementation package |
| `tests/` | Unit, integration, and regression tests |
| `scripts/` | WSL bootstrap and later experiment entry points |

## Reproducibility rules

- Never commit API keys, raw LLM conversations, downloaded datasets, or large experiment logs.
- Every real run must record git SHA, seed, prompt version, model, temperatures, budget ledger, dataset checksum, and environment export.
- Track `llm_calls`, `tokens`, `generated_candidates`, `valid_evals`, cost, and wall-clock time separately.
- CI uses only a mock LLM and small deterministic tests.
- Provider credentials, endpoints, and headers never belong in adapter config, logs, exceptions, or
  audit objects. The adapter does not read environment variables, `.env`, or keyrings.
- A real-model run must additionally record the adapter, prompt, tokenizer/token-counter, model, and
  pricing-table versions. Provider-reported usage is mandatory; local token counts cannot be used to
  invent billing usage.
- An EBBO oracle attempt counts as an `oracle_call` as soon as the oracle accepts it, even if it later
  fails, times out, is cancelled, or duplicates earlier work. EBBO oracle/evaluation/candidate/LLM/token/
  cost/wall-clock ledgers are implemented independently in P9a and remain separate from the existing
  Stage 2--5 `BudgetLedger`; no old ledger behavior was extended or reinterpreted.

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

## Stage 5 offline OpenAI-compatible adapter

`OpenAICompatibleProvider` implements the existing EoH and generation-local RoCo provider
interfaces. Its constructor requires an explicit transport, model-specific versioned token counter,
and versioned pricing table. The repository deliberately provides no HTTP client and the existing
CLI/smoke loader still accepts only Mock; omitting `llm.provider` also resolves to Mock.

The adapter sends one non-streaming, single-result strict JSON request, preserves each RoCo request's
prompt and temperature, and rejects missing/unknown fields, duplicate JSON keys, non-finite values,
multiple choices, mismatched models, and invalid usage. Calls are retried only for configured,
classified transient failures and never more than `max_retries + 1` attempts. Every transport-
accepted attempt counts as an LLM call. Valid provider usage drives input/output token and synthetic
test-cost accounting; missing or illegal usage closes the adapter path without substituting character
counts or zero cost.

Provider audits contain contract/model/token-counter/pricing versions, hashes, usage, cost, retry and
token-context decisions—not raw prompts, responses, request IDs, headers, or credentials. Context
truncation uses the injected token-counter contract and records every removed optional field; it does
not alter Stage 4's separate Mock character-budget behavior.

The independent `tests/unit/test_openai_compatible_provider.py` suite uses only scripted fake
responses and a fake token counter. Passing it means the adapter contract is offline-tested. It does
not establish HTTP/TLS/auth compatibility, validate a real tokenizer or price, evaluate model output
quality, or reproduce paper results. Any real transport, credential use, network call, or paid run
requires a separate explicit authorization and verification task.

## Stage 5 TSP protocol dry-run

The `tsp-dry-run` command creates or verifies a deterministic TSP-50/TSP-100/TSP-200 dataset manifest,
then executes the configured train/test, three-seed, prompt-visibility, and method matrix using only the
existing Mock provider. It writes a SHA-256-checked `dataset_manifest.json`, strict `results.jsonl` and
`results.csv`, plus descriptive `summary.jsonl` and `summary.csv`.

```bash
PYTHONPATH="$PWD/src" python -m roco_ebbo tsp-dry-run \
  --config configs/experiments/tsp_mock_dry_run.yaml \
  --output-dir /tmp/roco-tsp-dry-run
```

White-box and black-box are prompt-information visibility conditions, not expensive-oracle settings. The
first Mock run records both but intentionally makes no quality comparison. Each method receives identical
explicit hard ceilings; actual calls, tokens, candidates, valid evaluations, cost, and wall time remain
separately visible. The default inventory, seeds, timeout, bounds, and Mock measurements are engineering
protocol values, not paper data or performance reproduction. See
`docs/paper_spec/tsp_experiment_protocol.md`, ADR-0006, and G-034--G-036 before any real experiment.

## Stage 5 P7a multi-COP/statistics design

P7a registers TSP, MKP, OP, BPP, CVRP, and an unresolved `GLS` label as candidate COPs. ADR-0007 defines
E0--E4 evidence levels, while
`docs/paper_spec/multicop_experiment_protocol.md` freezes the cross-COP run record, fair-budget/split/
visibility/provider rules, and future statistical plan.

Query live Git for current HEAD, upstream, and publication state. P7a does not authorize network/provider
use, credentials, paid requests, performance claims, or statistical results.

## Stage 5 P7b FSU MKP offline protocol

P7b uses only the previously authorized John Burkardt/FSU `KNAPSACK_MULTIPLE` snapshot in the ignored
`data/raw/mkp/fsu-knapsack-multiple/` directory. `mkp-fsu-protocol-v1` verifies every raw byte against
the committed provenance contract, parses P01--P06 fail-closed, and marks all six instances
`protocol-only`: there is deliberately no train/validation/test or formal statistical use.

Candidate code returns one item-index list per knapsack. Duplicate assignment, out-of-range items,
capacity violations, malformed output, runtime failure, and timeout are structured failures. Source
profit is maximized, while the unchanged global Top-N path strictly minimizes `score=-raw_profit`.
Optional P01/P05/P06 reference files are never placed in prompts, never used for selection, and are not
claimed to be verified optima.

The sole visibility contract is versioned `full_instance` capacity/weight/profit information, not a
white/black comparison or expensive oracle. The engineering-only
`mkp-fsu-mock-engineering-v1` profile gives EoH and RoCo identical ceilings of 20 calls, 50000 Mock
tokens, 16 candidates, 16 valid evaluations, USD 0.25, and 60 seconds. With root seed 707, the 12-run
P01--P06 × EoH/RoCo matrix records EoH 8/8 and RoCo 18/13 actual calls/valid evaluations, manifest,
JSONL/CSV, raw/normalized audit values, six ledgers, and non-time replay checksums. It produces no
summary statistics, interval, ranking, cross-COP result, or model-performance claim.

```bash
PYTHONPATH="$PWD/src" python -m roco_ebbo mkp-dry-run \
  --config configs/experiments/mkp_fsu_mock_dry_run.yaml \
  --data-root data/raw/mkp/fsu-knapsack-multiple \
  --output-dir /tmp/roco-mkp-dry-run
```

This exact offline Mock contract is E3 evidence only. It does not authorize another download/COP,
reference optimality, G-041 statistical execution, a real provider, paper reproduction, or performance
and superiority conclusions. P7b implementation, commit, and publication status must be checked with
live Git rather than inferred from this historical working-tree note.

## Stage 6 EBBO: P8 design, P9a/P9b Mock, P9c fake-async Mock

ADR-0008 and `docs/paper_spec/ebbo_design.md` complete the published P8 design checkpoint. EBBO means
that objective and optional constraint feedback are available only through an expensive oracle; it is
not the paper's black-box prompt-visibility setting. The design freezes JSON-safe `OracleRequest`,
`OracleResult`, `Observation`, and `EvaluationStatus` concepts, acceptance-based oracle accounting,
stable IDs/seeds, replay boundaries, and modules for the oracle adapter, observation store, surrogate,
acquisition, finite candidate pool, scheduler, role controller, and artifacts.

The Stage 6 roles are global explorer, local exploiter, model critic, and resource integrator. They may
interpret observations, express region/strategy preferences, review uncertainty, and allocate budget.
They cannot call the oracle. In particular, the integrator can only select entries already produced by
the surrogate/acquisition candidate pool; the scheduler alone may dispatch after budget, constraint,
pending, and duplicate checks.

P9a is published by `4189f65970feab0a17299445641916c6245de4a8`. It
adds strict versioned JSON contracts and SHA-256 identities, an independent `ebbo-ledger-v1`, append-only
audit/Observation JSONL, a deterministic integer Mock domain, an offline Mock oracle, immutable finite
candidate pools, and the scheduler-only `max_concurrency=1` dispatch path. Accepted attempts immediately
consume `oracle_calls`; later failure, timeout, invalid result, unknown cost, or actual-cost overrun never
refunds the call. Preflight rejection, pre-accept cancellation, duplicates, and empty pools remain audited
without consuming a call.

The dependency-free single-agent engineering baseline is
`ebbo-nearest-observation-surrogate-v1` plus minimization
`ebbo-lower-confidence-bound-v1` (`mean - beta * normalized_distance_uncertainty`). The smoke uses the
finite integer domain `[-5,5]`, objective `(x-2)^2+1`, no constraints/no noise, `beta=2`, pool size 4,
root seed 9061, and fixed cost 1 `mock-evaluation-unit`. This is not a GP, calibrated probabilistic BO
model, paper method, external benchmark, or performance result.

The fixed smoke ledger is 5 accepted oracle calls, 5 successful/0 failed evaluations, 20 candidate
proposals, 5 `mock-evaluation-unit`, 0 LLM calls/tokens, 0 financial cost, and `network=unused`. Same-seed
runs reproduce pools, requests, results, Observations, discrete ledger state, and the non-time replay
checksum; wall-clock is deliberately excluded.

P9b adds versioned strict JSON role requests/responses, a deterministic injected fake provider, role-call/
synthetic-token accounting, an append-only permission/fallback audit, and a scheduler selection gate that
rechecks pool identity, membership, duplicate, Mock constraint/domain, and oracle budget before the
unchanged serial dispatch. Explorer/exploiter only name existing pool entry/region/strategy IDs; critic
reviews uncertainty/constraint/failure/cost risk; integrator only ranks/selects existing entry IDs.
Critic veto is configurable: advisory logs only, hard excludes vetoed entries. Invalid role output,
provider error/timeout, or role-budget exhaustion falls back to deterministic acquisition ordering;
if a valid hard veto removes every entry, dispatch stops. Role objects have no oracle capability.

The four-path offline smoke (full, no roles, no critic, no integrator) uses the same Mock oracle,
search space, root seed, initial state, finite-pool rule, and 5-call ceiling. Each path consumes 5
oracle calls, 20 proposals, and 5 Mock cost units; role calls are 20/0/15/15 respectively, with
financial cost 0 and `network=unused`. The no-role checksum remains the published P9a checksum
`7d4b4da802d2cd4e29742b74fa9e3866b4ab319a27d207e1ce4c8e79fac5da01`. These are
control-flow/replay facts, not performance evidence. P9b commit `fa3b464` is an ancestor of the
published P9c commit `b698649`.

P9c adds an opt-in, single-process deterministic fake-async scheduler (smoke concurrency 2),
outstanding call/expected-cost reservations, completion-order audit, cancellation acknowledgement,
and commit-last checkpoint/resume. Accepted Mock attempts are never refunded or dispatched twice;
actual-cost overrun is recorded even if it exceeds the admission ceiling, then closes new admission.
The smoke records 5 oracle calls, 3 successes, 2 failures (one timeout and one accepted cancellation),
20 proposals, 5 `mock-evaluation-unit`, zero LLM calls/tokens and financial cost, `network=unused`.
Its non-time replay checksum is `085fac4aa00ca567f055ab87b87084c896cfd463d5eb7a51741ccbae84e0e47f`;
checkpoint-boundary interruption/resume reproduces the same state and audit. This is not a real async
worker, probabilistic BO, cost-aware optimization, benchmark, or performance result.

P9c's local offline acceptance passed: 221 pytest tests passed, 1 skipped; Ruff check and format check,
mypy over 44 source files, doctor, the unchanged Stage 2/3/4 and P9a/P9b smoke contracts, the P9c
CLI smoke, and `git diff --check`. This verifies the offline Mock path only, not a real experiment.

The required implementation order is:

1. P9a: published by `4189f65970feab0a17299445641916c6245de4a8`.
2. P9b: restricted four-role Mock control, published as `fa3b464`.
3. P9c: opt-in fake-async pending/cancellation/recovery engineering Mock, published as `b698649`.
   Real async reconciliation and cost-aware acquisition remain open.
4. P10: use `docs/paper_spec/p10_experiment_preregistration_template.md` to record unset decisions;
   only after explicit authorization of benchmark, source, license, real provider/oracle, and hard
   budgets may a separate preregistered real experiment proceed.

Until P10 has E4 artifacts, the project makes no EBBO performance, significance, generalization, or
superiority claim and never aggregates raw scores across benchmarks.

## Original repository purpose

把 RoCo 发展成多智能体昂贵黑盒优化方法
