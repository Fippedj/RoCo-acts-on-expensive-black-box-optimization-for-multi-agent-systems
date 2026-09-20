"""Offline LLM provider and versioned RoCo role contracts."""

from roco_ebbo.llm.prompts import (
    PROMPT_VERSION,
    ROLE_PROMPTS,
    ROLE_TEMPERATURES,
    RoCoRole,
    prompt_for,
)
from roco_ebbo.llm.provider import (
    GeneratedHeuristic,
    LLMProvider,
    MemoryLLMProvider,
    MemoryMutationRequest,
    MemorySummaryRequest,
    MemorySummaryResponse,
    MockLLMProvider,
    RoleLLMProvider,
    RoleRequest,
    RoleResponse,
)

__all__ = [
    "PROMPT_VERSION",
    "ROLE_PROMPTS",
    "ROLE_TEMPERATURES",
    "GeneratedHeuristic",
    "LLMProvider",
    "MemoryLLMProvider",
    "MemoryMutationRequest",
    "MemorySummaryRequest",
    "MemorySummaryResponse",
    "MockLLMProvider",
    "RoCoRole",
    "RoleLLMProvider",
    "RoleRequest",
    "RoleResponse",
    "prompt_for",
]
