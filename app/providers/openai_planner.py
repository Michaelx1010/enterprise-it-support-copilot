"""OpenAI Structured Outputs planner. It proposes decisions, never executes tools."""

import os

from openai import APIError, OpenAI
from pydantic import ValidationError

from app.investigation.planner import INSTRUCTIONS, PlannerError, PlannerResponseV2, PlannerView, build_payload

DEFAULT_MODEL = 'gpt-4.1-mini-2025-04-14'
MAX_OUTPUT_TOKENS = 700
REQUEST_TIMEOUT = 30.0


class OpenAIPlanner:
    def __init__(self, client: OpenAI, *, model: str = DEFAULT_MODEL):
        if not model.strip():
            raise ValueError('Planner model must not be blank.')
        # Enforce one API attempt per graph decision, including injected clients.
        self.client = client.with_options(timeout=REQUEST_TIMEOUT, max_retries=0)
        self.model = model

    @classmethod
    def from_environment(cls) -> 'OpenAIPlanner':
        model = os.getenv('OPENAI_PLANNER_MODEL', DEFAULT_MODEL).strip()
        if not model:
            raise ValueError('Planner model must not be blank.')
        if not os.getenv('OPENAI_API_KEY', '').strip():
            raise ValueError('Set OPENAI_API_KEY locally before using the live planner.')
        return cls(OpenAI(timeout=REQUEST_TIMEOUT, max_retries=0), model=model)

    def decide(self, view: PlannerView, index: int) -> dict:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[{'role': 'system', 'content': INSTRUCTIONS},
                       {'role': 'user', 'content': build_payload(view, index)}],
                text_format=PlannerResponseV2, max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0, store=False,
            )
        except APIError:
            raise PlannerError('provider_failure') from None
        except (ValidationError, ValueError, TypeError):
            raise PlannerError('invalid_output') from None
        if response.status != 'completed':
            raise PlannerError('incomplete')
        messages = [item for item in response.output if item.type == 'message']
        if any(content.type == 'refusal' for item in messages for content in item.content):
            raise PlannerError('refusal')
        if any(item.type not in ('message', 'reasoning') for item in response.output):
            raise PlannerError('invalid_output')
        if response.output_parsed is None:
            raise PlannerError('missing_output')
        if len(messages) != 1 or len(messages[0].content) != 1 or messages[0].content[0].type != 'output_text':
            raise PlannerError('invalid_output')
        try:
            if not isinstance(response.output_parsed, PlannerResponseV2):
                raise ValueError('Unexpected parsed type.')
            # Revalidate mutated/substitute SDK objects without logging their values.
            result = PlannerResponseV2.model_validate(response.output_parsed.model_dump(warnings=False))
            return result.graph_decision()
        except (ValidationError, ValueError, TypeError):
            raise PlannerError('invalid_output') from None
