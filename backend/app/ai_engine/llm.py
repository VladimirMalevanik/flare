"""Language-model provider boundary."""

from typing import Protocol, Sequence


class LanguageModel(Protocol):
    model: str

    async def generate_insight(self, question: str, evidence: Sequence[str]) -> str: ...
