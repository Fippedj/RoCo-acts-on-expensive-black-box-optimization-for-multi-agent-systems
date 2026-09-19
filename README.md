# RoCo-EBBO

Method-level reproduction of **RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design**, followed by a migration toward multi-agent expensive black-box optimization (EBBO).

This repository contains a deterministic Stage 2 engineering baseline. It does **not** claim to be the authors' official implementation and does not yet contain the completed RoCo algorithm.

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
| `docs/RoCo_reproduction_and_EBBO_roadmap.md` | Six-stage reproduction and migration plan |
| `docs/paper/` | Source-grounded reading notes and paper-gap analysis |
| `configs/paper_defaults.yaml` | Paper-aligned settings, annotated with non-disclosed items |
| `configs/smoke/tsp_mock.yaml` | Cheap deterministic local-development configuration |
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

The current executable path is deliberately small and free of real API cost:

1. A seeded `MockLLMProvider` creates one structured candidate for each E1/E2/M1/M2 operator.
2. Candidate source is checked with a restrictive AST/function-signature allow-list.
3. `heuristic(distance_matrix) -> tour` executes only in a spawned subprocess with a per-candidate timeout.
4. Valid TSP-20 tours receive a closed-tour score; parents and children are merged and selected by deterministic Top-N.
5. The smoke preset initializes four candidates and runs two generations, for 12 mock calls and at most 12 valid evaluations.

Run manifests and JSONL event logs are written below the ignored `runs/` directory. The evaluator is only a development sandbox: it does not provide container, operating-system-user, syscall, filesystem, or network isolation and must not run untrusted code.

RoCo roles, collaboration, reflection/memory, real model providers, paper-scale evaluators, and EBBO are intentionally not implemented in Stage 2.
## Original repository purpose

把 RoCo 发展成多智能体昂贵黑盒优化方法
