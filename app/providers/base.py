"""The only interface a new model provider needs to implement."""

from typing import Protocol

from app.schemas import TicketClassification


class ClassificationError(RuntimeError):
    """The provider could not produce a valid classification."""


class ClassificationProvider(Protocol):
    def generate(self, *, instructions: str, ticket_text: str) -> TicketClassification:
        """Return validated output or raise ClassificationError."""
        ...
