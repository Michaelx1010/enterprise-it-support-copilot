"""Small offline fixtures for recommendation behavior, not model quality."""

import pytest

from app.kb.schemas import Chunk, SearchResult
from app.schemas import TicketInput


@pytest.fixture
def ticket():
    return TicketInput(subject="VPN unavailable", description="The Corporate gateway will not connect.")


@pytest.fixture
def evidence():
    return [SearchResult(distance=0.4, chunk=Chunk(
        chunk_id="vpn-chunk-1", document_id="vpn", source_path="vpn.md", title="VPN",
        section_id="vpn#connection", section_path="Connection", chunk_index=0,
        content="Select Corporate and reconnect once. Escalate persistent errors to Network Support.",
        content_hash="fixture-content-hash",
    ))]


@pytest.fixture
def recommendation_payload():
    return {
        "status": "supported", "summary": "The ticket reports a VPN connection failure.",
        "steps": [{"step_type": "troubleshooting", "action": "Select Corporate and reconnect once.",
                   "supporting_chunk_ids": ["vpn-chunk-1"]}],
        "missing_information": [], "escalation_required": False, "escalation_reason": None,
    }
