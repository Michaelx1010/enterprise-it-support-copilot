"""One-method synthesis boundary. No retrieval, tools, or SDK types."""

from typing import Protocol

from app.investigation.schemas import InvestigationSynthesis


class SynthesisError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__('Investigation synthesis failed: ' + code)


class SynthesisProvider(Protocol):
    def generate(self, *, instructions: str, payload: str) -> InvestigationSynthesis: ...
