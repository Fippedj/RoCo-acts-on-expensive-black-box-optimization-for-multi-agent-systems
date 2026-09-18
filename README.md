# RoCo-EBBO

Method-level reproduction of **RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design**, followed by a migration toward multi-agent expensive black-box optimization (EBBO).

This repository starts as a reproducible engineering scaffold. It does **not** claim to be the authors' official implementation and does not yet contain the completed RoCo algorithm.

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

See `docs/START_HERE.md` before writing Stage 1 code.
