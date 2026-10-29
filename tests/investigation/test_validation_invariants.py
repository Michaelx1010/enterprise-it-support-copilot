"""Invariant identities change; schemas, acceptance and provider failures do not."""

from copy import deepcopy
from hashlib import sha256
from itertools import product
import json

import httpx
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticCustomError
import pytest

from app.investigation.schemas import InvestigationResult, InvestigationSynthesis
from app.providers.openai_recommendation import OpenAIRecommendation
from app.providers.recommendation import RecommendationError
from app.rag.schemas import RecommendationResult, SupportRecommendation
from evaluation.live_investigation import project_report
from evaluation.synthesis_diagnostics import INVARIANT_TYPES, ParseObserver, error_details

VARIANTS = [
    ('supported_without_steps', 'status_steps_mismatch'),
    ('abstention_with_steps', 'status_steps_mismatch'),
    ('true_without_escalation_step', 'escalation_steps_mismatch'),
    ('false_with_escalation_step', 'escalation_steps_mismatch'),
    ('true_without_reason', 'escalation_reason_mismatch'),
    ('false_with_reason', 'escalation_reason_mismatch'),
    ('reason_without_kb', 'escalation_reason_missing_kb'),
]


def contradiction(valid: dict, variant: str) -> dict:
    candidate = deepcopy(valid)
    if variant == 'supported_without_steps':
        candidate['steps'] = []
    elif variant == 'abstention_with_steps':
        candidate['status'] = 'insufficient_evidence'
    else:
        candidate['escalation_required'] = variant != 'false_with_escalation_step' and variant != 'false_with_reason'
        candidate['escalation_reason'] = {'text': 'PRIVATE invariant test reason.',
                                         'references': deepcopy(candidate['steps'][0]['references'])}
        if variant not in ('true_without_escalation_step', 'false_with_reason'):
            candidate['steps'][0]['step_type'] = 'escalation'
        if variant in ('false_with_escalation_step', 'true_without_reason'):
            candidate['escalation_reason'] = None
        if variant == 'reason_without_kb':
            candidate['escalation_reason']['references'] = [{'kind': 'ticket'}]
    return candidate


class Envelope(BaseModel):
    report: InvestigationSynthesis


@pytest.mark.parametrize('variant,code', VARIANTS)
def test_invariants_survive_nested_validation_without_values(variant, code, synthesis_report):
    candidate = contradiction(synthesis_report, variant)
    for model, value, location in (
        (InvestigationSynthesis, candidate, ()), (Envelope, {'report': candidate}, ('report',)),
    ):
        with pytest.raises(ValidationError) as caught:
            model.model_validate(value)
        assert [(e['type'], e['loc']) for e in caught.value.errors()] == [(code, location)]
        details = error_details(caught.value)
        assert details['errors'][0]['type'] == code
        assert details['errors'][0]['loc'] == (['<redacted>'] if location else [])
        assert 'PRIVATE' not in json.dumps(details)


@pytest.mark.parametrize('variant,code', VARIANTS)
def test_sdk_still_validates_legacy_canonical_contract_with_identifiable_error(variant, code, synthesis_report,
        planner_client, planner_response):
    calls = []
    candidate = contradiction(synthesis_report, variant)
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    events = []
    observer = ParseObserver(planner_client(handler), events)
    with pytest.raises(ValidationError) as caught:
        observer.responses.parse(model='test-model', text_format=InvestigationSynthesis,
            input=[{'role': 'system', 'content': 'PRIVATE prompt'}, {'role': 'user', 'content': 'PRIVATE evidence'}])
    assert caught.value.errors()[0]['type'] == code
    assert len(calls) == 1
    assert calls[0]['input'] == [{'role': 'system', 'content': 'PRIVATE prompt'},
                                 {'role': 'user', 'content': 'PRIVATE evidence'}]
    assert calls[0]['text']['format']['schema'] == to_strict_json_schema(InvestigationSynthesis)
    assert events[0]['stage'] == 'sdk_parse'
    assert events[0]['errors'] == [{'type': code, 'loc': [], 'location_truncated': False}]
    assert 'PRIVATE' not in json.dumps(events)


@pytest.mark.parametrize('variant,code', VARIANTS[:-1])
def test_phase2_provider_and_nested_contract_preserve_rejection(variant, code, synthesis_report,
        planner_client, planner_response):
    candidate = project_report(contradiction(synthesis_report, variant))
    with pytest.raises(ValidationError) as nested:
        RecommendationResult.model_validate({'recommendation': candidate, 'evidence': []})
    assert [(e['type'], e['loc']) for e in nested.value.errors()] == [(code, ('recommendation',))]
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=planner_response(raw_text=json.dumps(candidate)))
    with pytest.raises(RecommendationError) as caught:
        OpenAIRecommendation(planner_client(handler)).generate(instructions='PRIVATE', payload='PRIVATE')
    assert caught.value.code == 'invalid_output' and caught.value.validation_types == [code]
    assert len(calls) == 1 and calls[0]['text']['format']['schema'] == to_strict_json_schema(SupportRecommendation)


@pytest.mark.parametrize('status,types,flag,reason_present', list(product(
    ('supported', 'insufficient_evidence'), ((), ('troubleshooting',), ('escalation',), ('troubleshooting', 'escalation')),
    (False, True), (False, True))))
def test_phase2_and_investigation_truth_table_parity(status, types, flag, reason_present, synthesis_report):
    candidate = deepcopy(synthesis_report)
    candidate.update(status=status, steps=[{**deepcopy(candidate['steps'][0]), 'step_type': t} for t in types],
        escalation_required=flag, escalation_reason={'text': 'Documented reason.',
            'references': deepcopy(synthesis_report['steps'][0]['references'])} if reason_present else None)
    # The pre-5C.1 truth table and first-failure precedence, not new relaxed rules.
    expected = ('status_steps_mismatch' if (status == 'supported') != bool(types) else
                'escalation_steps_mismatch' if flag != ('escalation' in types) else
                'escalation_reason_mismatch' if flag != reason_present else None)
    for model, value in ((InvestigationSynthesis, candidate), (SupportRecommendation, project_report(candidate))):
        if expected:
            with pytest.raises(ValidationError) as caught:
                model.model_validate(value)
            assert caught.value.errors()[0]['type'] == expected
        else:
            expected_value = value | {'conditional_guidance': [], 'trigger_basis': None} if model is InvestigationSynthesis else value
            assert model.model_validate(value).model_dump(mode='json') == expected_value


@pytest.mark.parametrize('code', sorted({code for _, code in VARIANTS}))
def test_only_exact_application_codes_are_allowed_never_their_messages(code):
    errors = ValidationError.from_exception_data('PRIVATE title', [
        {'type': PydanticCustomError(value, 'PRIVATE message {secret}', {'secret': 'PRIVATE credential'}),
         'loc': ('summary', 'PRIVATE key', 1), 'input': {'ticket': 'PRIVATE text'}}
        for value in (code, code + '_PRIVATE', 'PRIVATE_' + code)])
    details = error_details(errors)
    assert [e['type'] for e in details['errors']] == [code, 'other_validation_error', 'other_validation_error']
    assert all(e['loc'] == ['summary', '<redacted>', 1] for e in details['errors'])
    assert 'PRIVATE' not in json.dumps(details)


def test_allowlist_is_exact_and_other_validator_errors_stay_generic(synthesis_report):
    assert INVARIANT_TYPES == {code for _, code in VARIANTS} | {'escalation_trigger_mismatch'}
    candidate = deepcopy(synthesis_report)
    candidate['summary']['references'] *= 2
    with pytest.raises(ValidationError) as caught:
        InvestigationSynthesis.model_validate(candidate)
    assert error_details(caught.value)['errors'][0]['type'] == 'value_error'


# Canonical JSON Schema hashes captured before 5C.1 at a274774. No ignored reports
# or Git executable are needed in CI. Schema descriptions sent to models are covered.
SCHEMAS = [
    (SupportRecommendation, 'a73ef1e090b3ca069ad58580f81caec4fed551e8a9b914d532e14719aa3a4f87',
     'a73ef1e090b3ca069ad58580f81caec4fed551e8a9b914d532e14719aa3a4f87'),
    (RecommendationResult, '06126887131a44a1f865782cbbb920082cd35e0d453dd9f9a6159885ea5d2ed9',
     '88e829a5324121d9e595591774783785216810c17d69cc6b44b77d957a38f423'),
    (InvestigationSynthesis, 'ab0b6c4ed6557bb9c382e1cfa3161e69bb694043dec7874cf78937806b020d91',
     'f3d2af44a8cf486c66338842ddfe3152698f2439c03c95dea622dd2daf72812f'),
    (InvestigationResult, 'b2dbe2fd6b7a14fbc222a19323d2b7352854b45a03ba01e41c3ca61c95cca0cc',
     'ddf4946705c0d264201e76781ecb69948f7c7f4fd609e10c9bcdf84cea8f2b49'),
]


@pytest.mark.parametrize('model,expected,sdk_expected', SCHEMAS)
@pytest.mark.parametrize('mode', ['validation', 'serialization', 'sdk'])
def test_json_schemas_preserve_pre_change_fields_with_only_declared_extension(model, expected, sdk_expected, mode):
    schema = to_strict_json_schema(model) if mode == 'sdk' else model.model_json_schema(mode=mode)
    if model in (InvestigationSynthesis, InvestigationResult):
        # Check the declared additive field, then compare EVERY old field/definition
        # to the original hashes. Standalone Phase 2 schemas stay byte-for-byte equal.
        report = schema if model is InvestigationSynthesis else schema['$defs']['InvestigationSynthesis']
        trigger = report['properties'].pop('trigger_basis')
        assert trigger['anyOf'] == [{'$ref': '#/$defs/EscalationTriggerBasis'}, {'type': 'null'}]
        assert ('trigger_basis' in report['required']) == (mode == 'sdk')
        if mode == 'sdk': report['required'].remove('trigger_basis')
        else: assert trigger['default'] is None
        basis = schema['$defs'].pop('EscalationTriggerBasis')
        assert set(basis['properties']) == set(basis['required']) == {'policy_references', 'factual_references', 'explanation'}
        extension = report['properties'].pop('conditional_guidance')
        assert extension['type'] == 'array' and extension['maxItems'] == 4
        assert extension['items'] == {'$ref': '#/$defs/ConditionalGuidance'}
        assert ('conditional_guidance' in report['required']) == (mode == 'sdk')
        if mode == 'sdk': report['required'].remove('conditional_guidance')
        guidance = schema['$defs'].pop('ConditionalGuidance')
        assert set(guidance['properties']) == set(guidance['required']) == {'condition', 'action', 'references', 'missing_evidence'}
    assert sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() == (sdk_expected if mode == 'sdk' else expected)
