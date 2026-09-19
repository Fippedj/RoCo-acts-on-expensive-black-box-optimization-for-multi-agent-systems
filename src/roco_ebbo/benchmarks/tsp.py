"""Deterministic Euclidean TSP instance generation for the Stage 2 smoke test."""

from __future__ import annotations

import math
import random

DistanceMatrix = list[list[float]]


def generate_symmetric_distance_matrix(nodes: int = 20, seed: int = 0) -> DistanceMatrix:
    """Generate one seeded, symmetric Euclidean matrix with a zero diagonal."""

    if nodes < 2:
        raise ValueError("a TSP instance requires at least two nodes")
    rng = random.Random(seed)
    coordinates = [(rng.random(), rng.random()) for _ in range(nodes)]
    matrix = [[0.0 for _ in range(nodes)] for _ in range(nodes)]
    for first in range(nodes):
        for second in range(first + 1, nodes):
            distance = math.dist(coordinates[first], coordinates[second])
            matrix[first][second] = distance
            matrix[second][first] = distance
    return matrix


def tour_length(distance_matrix: DistanceMatrix, tour: list[int] | tuple[int, ...]) -> float:
    """Return the closed-tour length after validating matrix/tour dimensions."""

    nodes = len(distance_matrix)
    if nodes < 2 or any(len(row) != nodes for row in distance_matrix):
        raise ValueError("distance_matrix must be square and contain at least two nodes")
    if len(tour) != nodes:
        raise ValueError(f"tour must contain exactly {nodes} nodes")
    return sum(distance_matrix[tour[index]][tour[(index + 1) % nodes]] for index in range(nodes))
