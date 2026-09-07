"""Language-model provider boundary."""

from typing import Protocol, Sequence

from app.ai_engine.analysis import AnalysisResult, Evidence


class LanguageModel(Protocol):
    model: str

    async def generate_insight(self, question: str, evidence: Sequence[str]) -> str: ...


class TextAnalyzer(Protocol):
    """Analyze caller-authorized evidence without fetching or persisting context."""

    async def analyze(self, evidence: Sequence[Evidence]) -> AnalysisResult: ...
