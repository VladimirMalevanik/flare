"""Text extraction boundary for notes, links, audio and files."""

from typing import Protocol


class Extractor(Protocol):
    async def extract(self, content: bytes, content_type: str) -> str: ...
