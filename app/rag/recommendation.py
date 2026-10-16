"""Retrieve once, generate once, then reject structurally invalid answers."""

from pydantic import ValidationError

from app.kb import retrieval
from app.kb.schemas import SearchResult
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingProvider
from app.providers.recommendation import RecommendationError, RecommendationProvider
from app.rag.prompts import INSTRUCTIONS, build_payload
from app.rag.schemas import RecommendationResult, SupportRecommendation
from app.schemas import TicketInput


class InvalidCitationError(RecommendationError):
    """Retain the rejected candidate for evaluation, never as an accepted answer."""

    def __init__(self, candidate: SupportRecommendation) -> None:
        super().__init__("Recommendation cited evidence outside the retrieved results.",
                         code="invalid_citation")
        self.candidate = candidate


def build_query(ticket: TicketInput) -> str:
    ticket = TicketInput.model_validate(ticket.model_dump())
    query = f"Subject: {ticket.subject}\n\nDescription: {ticket.description}"
    if len(query) > 6000:
        raise ValueError("Ticket retrieval query exceeds 6000 characters; shorten the ticket.")
    return query


def retrieve_ticket(ticket: TicketInput, *, embedder: EmbeddingProvider,
                    store: PgvectorStore, top_k: int = 3) -> list[SearchResult]:
    return retrieval.search(build_query(ticket), embedder=embedder, store=store, top_k=top_k)


def generate_recommendation(ticket: TicketInput, evidence: list[SearchResult], *,
                            provider: RecommendationProvider) -> RecommendationResult:
    ticket = TicketInput.model_validate(ticket.model_dump())
    # Snapshot before handing text to a provider; returned source metadata is application-owned.
    evidence = [SearchResult.model_validate(item.model_dump()) for item in evidence]
    if not evidence:
        candidate = SupportRecommendation(
            status="insufficient_evidence",
            summary="No KB evidence was retrieved. Escalation need is undetermined; this is not a safety assessment.",
            steps=[], missing_information=["Relevant documentation is needed for this ticket."],
            escalation_required=False, escalation_reason=None,
        )
    else:
        try:
            candidate = provider.generate(instructions=INSTRUCTIONS, payload=build_payload(ticket, evidence))
            if not isinstance(candidate, SupportRecommendation):
                raise RecommendationError("Provider returned an invalid recommendation.", code="invalid_output")
            # Revalidate even if a substitute provider used model_construct or mutated a model.
            candidate = SupportRecommendation.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise RecommendationError(
                "Provider returned an invalid recommendation.", code="invalid_output",
                validation_types=sorted({error["type"] for error in exc.errors(include_input=False)}),
            ) from exc
    known_ids = {item.chunk.chunk_id for item in evidence}
    if any(chunk_id not in known_ids for step in candidate.steps for chunk_id in step.supporting_chunk_ids):
        raise InvalidCitationError(candidate)
    return RecommendationResult(recommendation=candidate, evidence=evidence)


def recommend(ticket: TicketInput, *, embedder: EmbeddingProvider, store: PgvectorStore,
              provider: RecommendationProvider, top_k: int = 3) -> RecommendationResult:
    evidence = retrieve_ticket(ticket, embedder=embedder, store=store, top_k=top_k)
    return generate_recommendation(ticket, evidence, provider=provider)
