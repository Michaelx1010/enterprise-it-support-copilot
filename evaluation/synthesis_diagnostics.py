"""Evaluation-only observation of unchanged synthesis validation boundaries.

No raw responses, exception messages/objects, prompts or input values are retained.
The SDK already runs application Pydantic validators during responses.parse().
Stage identifies where rejection happened, not whether the SDK is at fault.
"""

from typing import get_args

from openai import APIError
from pydantic import ValidationError
from pydantic_core import ErrorType

from app.investigation.schemas import InvestigationSynthesis
from app.providers.openai_synthesis import OpenAISynthesis
from app.providers.synthesis import SynthesisError

INVARIANT_TYPES = frozenset(('status_steps_mismatch', 'escalation_steps_mismatch',
                           'escalation_reason_mismatch', 'escalation_reason_missing_kb'))
KNOWN_TYPES = frozenset(get_args(ErrorType)) | INVARIANT_TYPES
SCHEMA = InvestigationSynthesis.model_json_schema()
KNOWN_LOCATIONS = frozenset(SCHEMA['properties']) | frozenset(SCHEMA.get('$defs', {})) | frozenset(
    key for definition in SCHEMA.get('$defs', {}).values() for key in definition.get('properties', {})) | {'schema_version'}
ERROR_CODES = frozenset(('provider_failure', 'invalid_output', 'invalid_citation', 'incomplete',
                         'refusal', 'missing_output', 'missing_limitations', 'context_limit', 'deadline'))


def error_details(error: BaseException | None) -> dict:
    if isinstance(error, ValidationError):
        errors = error.errors(include_input=False, include_context=False, include_url=False)
        return {'exception_type': 'pydantic_validation_error', 'error_count': len(errors),
                'errors_truncated': len(errors) > 20,
                'errors': [{'type': e['type'] if e['type'] in KNOWN_TYPES else 'other_validation_error',
                            'loc': [part if (type(part) is int and 0 <= part <= 1000)
                                    or (type(part) is str and part in KNOWN_LOCATIONS) else '<redacted>'
                                    for part in e['loc'][:12]],
                            'location_truncated': len(e['loc']) > 12} for e in errors[:20]]}
    kind = ('type_error' if isinstance(error, TypeError) else
            'value_error' if isinstance(error, ValueError) else
            'api_error' if isinstance(error, APIError) else 'unavailable')
    return {'exception_type': kind, 'error_count': None, 'errors': [], 'errors_truncated': False}


class ParseObserver:
    """Only the SDK methods used by OpenAISynthesis; credentials stay on its client."""

    def __init__(self, client, events: list[dict]):
        self._client, self._events = client, events
        self.responses = self

    def with_options(self, **options):
        return ParseObserver(self._client.with_options(**options), self._events)

    def parse(self, **kwargs):
        try:
            response = self._client.responses.parse(**kwargs)
        except Exception as exc:
            self._events.append({'stage': 'sdk_parse', 'outcome': 'failed', **error_details(exc)})
            raise  # Same exception reaches the unchanged production provider.
        self._events.append({'stage': 'sdk_parse', 'outcome': 'returned'})
        return response


class ObservedSynthesis:
    def __init__(self, provider):
        self.events: list[dict] = []
        self.returned = False
        # No SDK monkeypatching or global hooks. The shared client keeps its lifetime,
        # model, transport/proxy, timeout and zero retries. Other providers still work.
        self.provider = (OpenAISynthesis(ParseObserver(provider.client, self.events), model=provider.model)
                         if type(provider) is OpenAISynthesis else provider)

    def generate(self, *, instructions: str, payload: str):
        try:
            candidate = self.provider.generate(instructions=instructions, payload=payload)
        except SynthesisError as exc:
            if not any(e['stage'] == 'sdk_parse' and e['outcome'] == 'failed' for e in self.events):
                # `raise ... from None` hides traceback display, but Python retains the
                # immediate __context__. Extract only allowlisted details, not the object.
                context = exc.__context__
                stage = ('provider_revalidation' if exc.code == 'invalid_output'
                         and isinstance(context, (ValidationError, ValueError, TypeError))
                         else 'provider_response_validation')
                self.events.append({'stage': stage, 'outcome': 'failed',
                                    'code': exc.code if exc.code in ERROR_CODES else 'provider_failure',
                                    **error_details(context)})
            raise
        self.returned = True
        self.events.append({'stage': 'provider_validation', 'outcome': 'returned'})
        return candidate

    def finish(self, result) -> list[dict]:
        """Observe final application outcome without re-running any validation.

        The graph intentionally discards downstream exception details. Do not guess
        them or validate a second copy of the response merely for diagnostics.
        """
        if self.returned:
            code = next((e.code.removeprefix('synthesis_') for e in result.errors if e.stage == 'synthesis'), None)
            if code:
                stage = 'application_validation' if code in ('invalid_output', 'invalid_citation', 'missing_limitations') else 'pipeline_outcome'
                self.events.append({'stage': stage, 'outcome': 'failed',
                                    'code': code if code in ERROR_CODES else 'provider_failure',
                                    'details_available': False})
            elif result.synthesis_status == 'completed':
                self.events.append({'stage': 'application_validation', 'outcome': 'accepted'})
        return self.events
