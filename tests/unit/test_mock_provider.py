from __future__ import annotations

from roco_ebbo.core import BudgetLedger
from roco_ebbo.evolution import EOH_OPERATORS
from roco_ebbo.llm import MockLLMProvider


def test_mock_provider_is_seeded_reproducible_and_operator_specific() -> None:
    first_provider = MockLLMProvider(seed=123)
    second_provider = MockLLMProvider(seed=123)
    first_ledger = BudgetLedger(max_llm_calls=10, max_tokens=10_000)
    second_ledger = BudgetLedger(max_llm_calls=10, max_tokens=10_000)

    first = [
        first_provider.generate(operator, generation=0, parents=(), ledger=first_ledger)
        for operator in EOH_OPERATORS
    ]
    second = [
        second_provider.generate(operator, generation=0, parents=(), ledger=second_ledger)
        for operator in EOH_OPERATORS
    ]

    assert first == second
    assert len({response.code for response in first}) == 4
    assert first_ledger.to_dict() == second_ledger.to_dict()
    assert first_ledger.llm_calls == 4
    assert first_ledger.generated_candidates == 4
    assert first_ledger.cost == 0.0
