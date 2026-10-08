"""Provider-independent ticket inputs and classification contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "Software", "Account", "Network", "Security", "Communication", "Hardware",
    "RemoteWork", "Training", "Infrastructure", "Licensing", "Performance",
]
Priority = Literal["Low", "Medium", "High", "Urgent"]


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TicketClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: Category
    priority: Priority
    summary: str = Field(
        min_length=1,
        max_length=400,
        description="One concise sentence describing the issue, without invented facts.",
    )
