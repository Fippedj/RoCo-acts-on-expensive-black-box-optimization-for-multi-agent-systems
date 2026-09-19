from __future__ import annotations

from roco_ebbo.core import Candidate
from roco_ebbo.evolution import Population


def _candidate(candidate_id: str, score: float | None) -> Candidate:
    return Candidate(
        id=candidate_id,
        description="test",
        code="def heuristic(distance_matrix):\n    return []\n",
        parents=(),
        operator="E1",
        generation=0,
        score=score,
    )


def test_population_top_n_is_deterministic_and_excludes_invalid_candidates() -> None:
    population = Population.select_top_n(
        [
            _candidate("b", 2.0),
            _candidate("invalid", None),
            _candidate("c", 3.0),
            _candidate("a", 2.0),
        ],
        size=2,
        minimize=True,
    )

    assert [candidate.id for candidate in population.candidates] == ["a", "b"]
