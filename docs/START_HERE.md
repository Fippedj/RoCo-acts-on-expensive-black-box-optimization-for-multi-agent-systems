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
