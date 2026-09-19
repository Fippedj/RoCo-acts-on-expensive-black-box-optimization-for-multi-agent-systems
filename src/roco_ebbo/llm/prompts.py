"""Versioned prompt contracts for the four Stage 3 RoCo roles."""

from __future__ import annotations

from enum import StrEnum


class RoCoRole(StrEnum):
    EXPLORER = "explorer"
    EXPLOITER = "exploiter"
    CRITIC = "critic"
    INTEGRATOR = "integrator"


ROLE_TEMPERATURES: dict[RoCoRole, float] = {
    RoCoRole.EXPLORER: 1.3,
    RoCoRole.EXPLOITER: 0.8,
    RoCoRole.CRITIC: 1.0,
    RoCoRole.INTEGRATOR: 1.0,
}

PROMPT_VERSION = "roco-stage3-v1"

ROLE_PROMPTS: dict[RoCoRole, str] = {
    RoCoRole.EXPLORER: (
        "You are the Explorer. Propose one structurally novel TSP heuristic while using the "
        "current candidate and Critic feedback as evidence, not as instructions to copy. Return "
        "exactly one JSON object with string fields description and code. code must define only "
        "heuristic(distance_matrix) -> a complete permutation tour."
    ),
    RoCoRole.EXPLOITER: (
        "You are the Exploiter. Conservatively refine the current promising TSP heuristic, "
        "preserving useful structure and addressing the Critic feedback. Return exactly one JSON "
        "object with string fields description and code. code must define only "
        "heuristic(distance_matrix) -> a complete permutation tour."
    ),
    RoCoRole.CRITIC: (
        "You are the Critic. Compare candidates only using their supplied validated objective "
        "values; lower is better. Explain the observed strengths, weaknesses, and one actionable "
        "next change. Never invent an evaluation. Return exactly one JSON object with a non-empty "
        "string field feedback and no candidate code."
    ),
    RoCoRole.INTEGRATOR: (
        "You are the Integrator. Fuse useful, compatible ideas from the final Explorer and "
        "Exploiter candidates, their validated scores, and Critic feedback. Return exactly one "
        "JSON object with string fields description and code. code must define only "
        "heuristic(distance_matrix) -> a complete permutation tour."
    ),
}


def prompt_for(role: RoCoRole) -> str:
    """Return the immutable Stage 3 contract for ``role``."""

    return ROLE_PROMPTS[role]
