"""The four prompt operators used by the minimal EoH baseline."""

from __future__ import annotations

from enum import StrEnum


class EoHOperator(StrEnum):
    E1 = "E1"
    E2 = "E2"
    M1 = "M1"
    M2 = "M2"


EOH_OPERATORS: tuple[EoHOperator, ...] = tuple(EoHOperator)
