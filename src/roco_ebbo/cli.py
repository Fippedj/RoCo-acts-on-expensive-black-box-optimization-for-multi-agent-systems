"""Command-line diagnostics and deterministic offline smoke execution."""

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
    smoke = subparsers.add_parser(
        "smoke", help="run an offline deterministic TSP-20 EoH or RoCo loop"
    )
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
        print("status=stage3-roco-ready; provider=mock; network=unused")
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

    smoke_run = run_smoke(
        settings,
        memory_root=(run_directory / "memory") if settings.memory_enabled else None,
        run_id=run_id,
    )
    trace_path = run_directory / "collaboration_trace.jsonl"
    if smoke_run.result.collaboration_traces:
        for collaboration_trace in smoke_run.result.collaboration_traces:
            _append_event(trace_path, collaboration_trace.to_dict())
    memory_trace_path = run_directory / "memory_runtime_trace.jsonl"
    if smoke_run.result.memory_traces:
        for memory_trace in smoke_run.result.memory_traces:
            _append_event(memory_trace_path, memory_trace.to_dict())
    budget_snapshot = smoke_run.ledger.to_dict()
    resolved_seeds: dict[str, int] = {
        "mock_provider": smoke_run.provider_seed,
        "tsp_instance": smoke_run.benchmark_seed,
    }
    if smoke_run.collaboration_seed is not None:
        resolved_seeds["roco_collaboration"] = smoke_run.collaboration_seed
    config_snapshot = {**settings.config_snapshot, "resolved_seeds": resolved_seeds}
    if settings.mode == "roco":
        config_snapshot["resolved_stage3"] = {
            "mode": settings.mode,
            "collaboration_rounds": settings.collaboration_rounds,
            "elite_sampling_power": settings.elite_sampling_power,
            "temperatures": {
                role.value: value for role, value in settings.role_temperatures.items()
            },
        }
    if settings.memory_enabled:
        config_snapshot["resolved_stage4_memory"] = {
            "recent_events": settings.memory_recent_events,
            "success_slots": settings.memory_success_slots,
            "failure_slots": settings.memory_failure_slots,
            "elite_count": settings.memory_elite_count,
            "max_context_characters": settings.memory_max_context_characters,
        }
    manifest = RunManifest(
        seed=settings.seed,
        git_sha=_git_sha(),
        config_snapshot=config_snapshot,
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
        "mode": settings.mode,
        "scope": (
            "stage4-offline-reflection-memory-mock"
            if settings.memory_enabled
            else (
                "stage3-generation-local-roco-mock"
                if settings.mode == "roco"
                else "stage2-minimal-eoh-mock-only"
            )
        ),
        "collaboration_trace": (trace_path.name if smoke_run.result.collaboration_traces else None),
        "collaboration_generations": len(smoke_run.result.collaboration_traces),
        "memory_enabled": settings.memory_enabled,
        "memory_runtime_trace": (
            memory_trace_path.name if smoke_run.result.memory_traces else None
        ),
        "memory_generations": len(smoke_run.result.memory_traces),
        "memory_root": "memory" if smoke_run.result.memory_traces else None,
    }
    if settings.mode == "eoh":
        summary["stage2_scope"] = "minimal-eoh-mock-only"
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
            "mode": settings.mode,
            "collaboration_generations": len(smoke_run.result.collaboration_traces),
            "memory_generations": len(smoke_run.result.memory_traces),
        },
    )

    print(f"run_id={run_id}")
    print(f"best_score={smoke_run.result.population.best.score:.12f}")
    print(f"valid_evaluations={smoke_run.ledger.valid_evals}")
    print(f"llm_calls={smoke_run.ledger.llm_calls}")
    print(f"budget_reached={str(smoke_run.ledger.budget_reached).lower()}")
    print(f"mode={settings.mode}")
    if smoke_run.result.collaboration_traces:
        print(f"collaboration_trace={trace_path}")
    if smoke_run.result.memory_traces:
        print(f"memory_runtime_trace={memory_trace_path}")
        print(f"memory_root={run_directory / 'memory'}")


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
