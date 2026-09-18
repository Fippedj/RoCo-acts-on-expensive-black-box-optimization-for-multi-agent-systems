#!/usr/bin/env bash
set -euo pipefail

conda env create -f environment.yml || conda env update -f environment.yml --prune
conda run -n roco-dev python -m pip install -e '.[dev,llm]'
conda run -n roco-dev python -m pytest
echo "Done. Activate with: conda activate roco-dev"
