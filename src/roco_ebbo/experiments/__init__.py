"""Offline, replayable experiment protocols.

The package deliberately contains protocol and accounting infrastructure only.
It does not construct a network provider or make a performance claim.
"""

from roco_ebbo.experiments.tsp_protocol import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    TSPDatasetManifest,
    TSPDatasetSpec,
    TSPExperimentResult,
    TSPExperimentRun,
    TSPExperimentSettings,
    TSPExperimentSummary,
    TSPInstance,
    TSPProtocolError,
    aggregate_results,
    create_dataset_manifest,
    execute_tsp_experiment,
    load_dataset_manifest,
    load_tsp_experiment_settings,
    read_results_jsonl,
    write_experiment_artifacts,
)

__all__ = [
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "TSPExperimentResult",
    "TSPExperimentRun",
    "TSPExperimentSettings",
    "TSPExperimentSummary",
    "TSPDatasetManifest",
    "TSPDatasetSpec",
    "TSPInstance",
    "TSPProtocolError",
    "aggregate_results",
    "create_dataset_manifest",
    "execute_tsp_experiment",
    "load_dataset_manifest",
    "load_tsp_experiment_settings",
    "read_results_jsonl",
    "write_experiment_artifacts",
]
