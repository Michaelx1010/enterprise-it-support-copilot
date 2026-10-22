"""One OpenAI Structured Outputs attempt; no tool execution or repair loop."""

import os

from openai import APIError, OpenAI
from pydantic import ValidationError

from app.investigation.schemas import InvestigationSynthesis
from app.providers.synthesis import SynthesisError

DEFAULT_MODEL = 'gpt-4.1-mini-2025-04-14'
MAX_OUTPUT_TOKENS = 3000
REQUEST_TIMEOUT = 30.0


class OpenAISynthesis:
    def __init__(self, client: OpenAI, *, model: str = DEFAULT_MODEL):
        if not model.strip():
            raise ValueError('Synthesis model must not be blank.')
        self.client = client.with_options(timeout=REQUEST_TIMEOUT, max_retries=0)
        self.model = model

    @classmethod
    def from_environment(cls, client: OpenAI) -> 'OpenAISynthesis':
        # The CLI owns the shared client's credentials and lifetime.
        return cls(client, model=os.getenv('OPENAI_SYNTHESIS_MODEL', DEFAULT_MODEL).strip())

    def generate(self, *, instructions: str, payload: str) -> InvestigationSynthesis:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[{'role': 'system', 'content': instructions}, {'role': 'user', 'content': payload}],
                text_format=InvestigationSynthesis, max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0, store=False,
            )
        except APIError:
            raise SynthesisError('provider_failure') from None
        except (ValidationError, ValueError, TypeError):
            raise SynthesisError('invalid_output') from None
        if response.status != 'completed':
            raise SynthesisError('incomplete')
        messages = [item for item in response.output if item.type == 'message']
        if any(c.type == 'refusal' for item in messages for c in item.content):
            raise SynthesisError('refusal')
        if any(item.type not in ('message', 'reasoning') for item in response.output):
            raise SynthesisError('invalid_output')
        if response.output_parsed is None:
            raise SynthesisError('missing_output')
        if len(messages) != 1 or len(messages[0].content) != 1 or messages[0].content[0].type != 'output_text':
            raise SynthesisError('invalid_output')
        try:
            if not isinstance(response.output_parsed, InvestigationSynthesis):
                raise ValueError('Unexpected parsed type.')
            return InvestigationSynthesis.model_validate(response.output_parsed.model_dump())
        except (ValidationError, ValueError, TypeError):
            raise SynthesisError('invalid_output') from None
