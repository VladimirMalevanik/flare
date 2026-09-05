"""Embedding provider boundary."""

from typing import Protocol, Sequence


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
