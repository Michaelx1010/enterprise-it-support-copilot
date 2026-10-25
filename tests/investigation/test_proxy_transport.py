"""Real HTTPX transport configuration with fake httpcore pools: no sockets/API calls."""

import json
import inspect
import os

import httpcore
import httpx
import pytest

from evaluation import live_telemetry as telemetry

# The shared test fixture blocks this method. Restore it only over fake pools.
TRANSPORT_SEND = httpx.HTTPTransport.handle_request


@pytest.fixture
def pools(monkeypatch):
    for key in tuple(os.environ):
        if key.lower() in ('https_proxy', 'http_proxy', 'all_proxy', 'no_proxy'):
            monkeypatch.delenv(key)
    created = []

    class Pool:
        def __init__(self, route, **kwargs):
            self.route, self.options = route, kwargs
            self.requests = []
            self.closed = False
            self.fail = False
            self.status = 401
            created.append(self)

        def handle_request(self, request):
            self.requests.append(request)
            if self.fail:
                raise httpcore.ConnectError('proxy-user:proxy-secret must never be logged')
            headers = [(b'location', b'https://untrusted.invalid/')] if self.status == 302 else []
            return httpcore.Response(self.status, headers=headers, content=b'{"error":{"message":"not authorized"}}')

        def close(self):
            self.closed = True

    # HTTPX passes retries explicitly for direct pools; HTTPProxy uses its default.
    proxy_retries = inspect.signature(httpcore.HTTPProxy).parameters['retries'].default
    def proxy_pool(**kwargs):
        kwargs.setdefault('retries', proxy_retries)
        return Pool('proxy', **kwargs)
    monkeypatch.setattr(httpcore, 'HTTPProxy', proxy_pool)
    monkeypatch.setattr(httpcore, 'ConnectionPool', lambda **kw: Pool('direct', **kw))
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', TRANSPORT_SEND)
    return created


@pytest.mark.parametrize('environment, route, host', [
    ({'HTTPS_PROXY': 'http://https-proxy.invalid:7897'}, 'proxy', b'https-proxy.invalid'),
    ({'ALL_PROXY': 'http://all-proxy.invalid:7897'}, 'proxy', b'all-proxy.invalid'),
    ({'https_proxy': 'http://lower-proxy.invalid:7897'}, 'proxy', b'lower-proxy.invalid'),
    ({'all_proxy': 'http://lower-all.invalid:7897'}, 'proxy', b'lower-all.invalid'),
    ({'HTTPS_PROXY': 'http://https-proxy.invalid:7897', 'ALL_PROXY': 'http://all-proxy.invalid:7897'}, 'proxy', b'https-proxy.invalid'),
    ({'HTTPS_PROXY': 'http://proxy.invalid:7897', 'NO_PROXY': 'api.openai.com'}, 'direct', None),
    ({'ALL_PROXY': 'http://proxy.invalid:7897', 'NO_PROXY': '.openai.com'}, 'direct', None),
    ({'HTTPS_PROXY': 'http://proxy.invalid:7897', 'NO_PROXY': '*'}, 'direct', None),
    ({'HTTPS_PROXY': 'http://proxy.invalid:7897', 'NO_PROXY': 'unrelated.invalid'}, 'proxy', b'proxy.invalid'),
    ({'HTTP_PROXY': 'http://http-only.invalid:7897'}, 'direct', None),
    ({}, 'direct', None),
])
def test_metered_request_reaches_configured_pool(pools, monkeypatch, environment, route, host):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    meter = telemetry.openai_transport()
    with httpx.Client(transport=meter) as client:
        response = client.post(telemetry.API_BASE_URL + '/responses', json={
            'model': 'test-model', 'text': {'format': {'name': 'PlannerResponse'}}, 'input': 'private ticket'})
    assert response.status_code == 401
    assert len(pools) == 1 and pools[0].route == route and pools[0].closed
    if host:
        assert pools[0].options['proxy_url'].host == host
    assert pools[0].options['retries'] == 0
    assert len(pools[0].requests) == len(meter.calls) == 1
    assert pools[0].requests[0].url.host == b'api.openai.com'
    assert meter.calls[0]['stage'] == 'planner' and meter.calls[0]['http_status'] == 401
    assert meter.calls[0]['usage'] is None
    assert 'private ticket' not in json.dumps(meter.calls)


def test_proxy_credentials_are_used_only_by_transport(pools, monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy-user:proxy-secret@proxy.invalid:7897')
    meter = telemetry.openai_transport()
    with httpx.Client(transport=meter) as client:
        client.get(telemetry.API_BASE_URL + '/models')
    assert pools[0].options['proxy_auth'] == (b'proxy-user', b'proxy-secret')
    assert 'proxy-secret' not in json.dumps(meter.calls)
    assert 'proxy-user' not in json.dumps(meter.calls)


@pytest.mark.parametrize('fail', [False, True])
def test_connectivity_check_uses_same_proxy_without_auth_or_fallback(pools, monkeypatch, capsys, fail):
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy-user:proxy-secret@proxy.invalid:7897')
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-test-key')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://untrusted.invalid')
    original = telemetry.openai_transport
    def factory():
        meter = original()
        pools[0].fail = fail
        return meter
    monkeypatch.setattr(telemetry, 'openai_transport', factory)
    assert telemetry.check_connectivity() == (1 if fail else 0)
    output = capsys.readouterr().out
    assert all(secret not in output for secret in ('proxy-user', 'proxy-secret', 'unused-test-key'))
    assert json.loads(output)['paid_api_calls'] == 0
    assert len(pools) == len(pools[0].requests) == 1
    request = pools[0].requests[0]
    assert request.method == b'GET' and request.url.host == b'api.openai.com'
    assert request.url.target == b'/v1/models'
    assert not any(k.lower() in (b'authorization', b'proxy-authorization') for k, v in request.headers)
    assert b''.join(request.stream) == b''
    assert pools[0].closed and pools[0].options['retries'] == 0


def test_connectivity_check_does_not_follow_redirect(pools, monkeypatch, capsys):
    original = telemetry.openai_transport
    def factory():
        meter = original()
        pools[0].status = 302
        return meter
    monkeypatch.setattr(telemetry, 'openai_transport', factory)
    assert telemetry.check_connectivity() == 1
    assert len(pools[0].requests) == 1
    assert json.loads(capsys.readouterr().out)['http_status'] == 302


def test_proxy_setup_errors_do_not_expose_credentials(pools, monkeypatch, capsys):
    monkeypatch.setenv('HTTPS_PROXY', 'unsupported://proxy-user:proxy-secret@proxy.invalid')
    assert telemetry.check_connectivity() == 1
    output = capsys.readouterr().out
    assert 'proxy-user' not in output and 'proxy-secret' not in output
    assert json.loads(output)['error'] == 'connectivity_check_failed'
    assert not pools  # No request, retry or fallback on invalid configuration.
