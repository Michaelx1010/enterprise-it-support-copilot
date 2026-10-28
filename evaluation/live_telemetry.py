"""Evaluation-only HTTP accounting; never retain headers, prompts or error bodies."""

import json
import time
from urllib.request import getproxies_environment, proxy_bypass_environment

import httpx

API_BASE_URL = 'https://api.openai.com/v1'


def openai_transport() -> 'MeteredTransport':
    """Resolve environment routing for our single fixed HTTPS destination.

    An explicit HTTPX transport disables the client's automatic proxy mounts.
    Put the proxy on the inner transport so no request bypasses metering.
    Never retain proxy configuration in telemetry or diagnostics.
    """
    proxies = getproxies_environment()
    proxy = None if proxy_bypass_environment('api.openai.com', proxies) else (
        proxies.get('https') or proxies.get('all'))
    return MeteredTransport(httpx.HTTPTransport(proxy=proxy, retries=0))


class MeteredTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport):
        self.transport = transport
        self.calls: list[dict] = []
        self.case_id: str | None = None
        self.arm = 'agent'

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        schema = payload.get('text', {}).get('format', {}).get('name')
        stage = {'TicketClassification': 'classification', 'PlannerResponse': 'planner',
                 'InvestigationSynthesis': 'synthesis', 'InvestigationSynthesisDraftV1': 'synthesis',
                 'SupportRecommendation': 'recommendation'}.get(
                     schema, 'connectivity' if request.method == 'GET' else 'embedding')
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


def check_connectivity() -> int:
    """One unauthenticated GET through the evaluator transport; never use the SDK."""
    try:
        meter = openai_transport()
        with httpx.Client(transport=meter, timeout=10.0, follow_redirects=False) as client:
            response = client.get(API_BASE_URL + '/models')
        print(json.dumps({'authenticated': False, 'paid_api_calls': 0,
                          'http_status': response.status_code, 'expected_unauthorized': response.status_code == 401,
                          'requests': len(meter.calls), 'latency_seconds': meter.calls[0]['latency_seconds']}))
        return 0 if response.status_code == 401 else 1
    except Exception:
        # Proxy errors may contain credentials. Never echo exception text or URLs.
        print(json.dumps({'authenticated': False, 'paid_api_calls': 0, 'error': 'connectivity_check_failed'}))
        return 1


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Unauthenticated check using the Phase 5B metered transport.')
    parser.add_argument('--check-connectivity', action='store_true', required=True)
    parser.parse_args()
    raise SystemExit(check_connectivity())
