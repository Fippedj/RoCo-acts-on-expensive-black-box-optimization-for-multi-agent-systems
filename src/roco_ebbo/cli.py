"""Command-line diagnostics and deterministic Stage 2 smoke execution."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from roco_ebbo import __version__
from roco_ebbo.core import RunManifest
from roco_ebbo.smoke import load_smoke_settings, run_smoke


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roco-ebbo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="print environment information for a bug report")
    smoke = subparsers.add_parser("smoke", help="run the offline deterministic TSP-20 EoH loop")
    smoke.add_argument("--config", required=True, type=Path, help="path to the smoke YAML config")
    smoke.add_argument(
        "--runs-dir",
        default=Path("runs"),
        type=Path,
        help="ignored output root for logs and manifests (default: runs)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "doctor":
        print(f"roco-ebbo={__version__}")
        print(f"python={sys.version.split()[0]}")
        print(f"platform={platform.platform()}")
        print("status=stage2-eoh-mvp-ready; provider=mock; network=unused")
        return
    if args.command == "smoke":
        _run_smoke_command(args.config, args.runs_dir)


def _run_smoke_command(config_path: Path, runs_dir: Path) -> None:
    settings = load_smoke_settings(config_path)
    run_id = _new_run_id(settings.seed)
    run_directory = runs_dir / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    events_path = run_directory / "events.jsonl"
    _append_event(events_path, {"event": "run_started", "run_id": run_id})

    smoke_run = run_smoke(settings)
    budget_snapshot = smoke_run.ledger.to_dict()
    manifest = RunManifest(
        seed=settings.seed,
        git_sha=_git_sha(),
        config_snapshot={
            **settings.config_snapshot,
            "resolved_seeds": {
                "mock_provider": smoke_run.provider_seed,
                "tsp_instance": smoke_run.benchmark_seed,
            },
        },
        environment_information={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "roco_ebbo": __version__,
            "llm_provider": "mock",
        },
        budget_snapshot=budget_snapshot,
    )
    manifest.write_json(run_directory / "manifest.json")
    summary = {
        "run_id": run_id,
        "best_candidate_id": smoke_run.result.population.best.id,
        "best_score": smoke_run.result.population.best.score,
        "population_size": len(smoke_run.result.population.candidates),
        "generations_completed": smoke_run.result.generations_completed,
        "budget": budget_snapshot,
        "stage2_scope": "minimal-eoh-mock-only",
    }
    (run_directory / "summary.json").write_text(
        f"{json.dumps(summary, allow_nan=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    _append_event(
        events_path,
        {
            "event": "run_completed",
            "run_id": run_id,
            "best_score": smoke_run.result.population.best.score,
            "budget": budget_snapshot,
        },
    )

    print(f"run_id={run_id}")
    print(f"best_score={smoke_run.result.population.best.score:.12f}")
    print(f"valid_evaluations={smoke_run.ledger.valid_evals}")
    print(f"llm_calls={smoke_run.ledger.llm_calls}")
    print(f"budget_reached={str(smoke_run.ledger.budget_reached).lower()}")


def _new_run_id(seed: int) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"smoke-{timestamp}-s{seed}-{uuid.uuid4().hex[:8]}"


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, allow_nan=False, sort_keys=True))
        stream.write("\n")
