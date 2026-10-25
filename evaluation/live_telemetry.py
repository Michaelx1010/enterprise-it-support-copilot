"""Evaluation-only HTTP accounting; never retain headers, prompts or error bodies."""

import json
import time

import httpx


class MeteredTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport):
        self.transport = transport
        self.calls: list[dict] = []
        self.case_id: str | None = None
        self.arm = 'agent'

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        schema = payload.get('text', {}).get('format', {}).get('name')
        stage = {'TicketClassification': 'classification', 'PlannerResponse': 'planner',
                 'InvestigationSynthesis': 'synthesis', 'SupportRecommendation': 'recommendation'}.get(schema, 'embedding')
        row = {'case_id': self.case_id, 'arm': self.arm, 'stage': stage,
               'model_requested': payload.get('model'), 'model_returned': None,
               'settings': {k: payload[k] for k in ('max_output_tokens', 'temperature', 'store', 'dimensions') if k in payload},
               'http_status': None, 'usage': None, 'cost_usd': None,
               'cost_note': 'API response does not report billed cost; no price estimate configured.',
               'error': None}
        started = time.monotonic()
        try:
            response = self.transport.handle_request(request)
            response.read()
            row['http_status'] = response.status_code
            if response.is_success:
                try:
                    body = response.json()
                    model = body.get('model')
                    row['model_returned'] = model if isinstance(model, str) else None
                    usage = body.get('usage')
                    if isinstance(usage, dict):
                        # Copy counts only, including cache/reasoning counts when supplied.
                        row['usage'] = {k: v for k, v in usage.items()
                                        if k in ('input_tokens', 'output_tokens', 'total_tokens', 'prompt_tokens')
                                        and type(v) is int and v >= 0}
                        for key in ('input_tokens_details', 'output_tokens_details'):
                            details = usage.get(key)
                            if isinstance(details, dict):
                                row['usage'][key] = {k: v for k, v in details.items()
                                    if k in ('cached_tokens', 'reasoning_tokens') and type(v) is int and v >= 0}
                except (ValueError, TypeError, AttributeError):
                    row['error'] = 'unreadable_response_metadata'
            else:
                row['error'] = 'http_error'
            return response
        except Exception:
            row['error'] = 'transport_failure'
            raise
        finally:
            row['latency_seconds'] = time.monotonic() - started
            self.calls.append(row)

    def close(self) -> None:
        self.transport.close()


def usage_totals(calls: list[dict]) -> dict:
    known = [r['usage']['total_tokens'] for r in calls
             if r['usage'] is not None and 'total_tokens' in r['usage']]
    return {'requests': len(calls), 'known_total_tokens': sum(known),
            'requests_without_total_tokens': len(calls) - len(known), 'cost_usd': None}
