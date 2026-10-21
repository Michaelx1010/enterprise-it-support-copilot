from copy import deepcopy
from pathlib import Path

import pytest

from app.investigation.graph import Dependencies
from app.investigation.schemas import InvestigationRequest
from app.investigation.scripted import ReplayStore, ScriptedClassifier, ScriptedEmbedder, ScriptedPlanner
from app.kb.documents import load_chunks
from app.kb.schemas import SearchResult
from app.operations import queries
from app.operations.seed import load_seed
from app.providers.embeddings import EmbeddingSpec
from app.rag.recommendation import build_query
from app.schemas import TicketClassification, TicketInput


@pytest.fixture
def inv_request():
    return InvestigationRequest(ticket=TicketInput(subject='VPN cannot connect', description='The connection fails after sign in.'),
                                employee_id='EMP-001', service_ids=['SVC-001'], software_ids=['SW-001'])


@pytest.fixture
def inv_results():
    tables = load_seed()
    def row(table, columns, index=0):
        value = tables[table][index].model_dump(mode='json')
        return {key: value[key] for key in columns.split(',')}
    employee = row('employees', queries.EMPLOYEE_COLUMNS)
    device = row('devices', queries.DEVICE_COLUMNS)
    common = {'status': 'ok', 'missing_entities': [], 'queried_at': '2026-10-21T08:00:00Z'}
    return {
        'get_employee_account_status': common | {'employee': employee, 'account': row('accounts', queries.ACCOUNT_COLUMNS)},
        'get_employee_devices': common | {'employee': employee, 'devices': [device, row('devices', queries.DEVICE_COLUMNS, 9)]},
        'get_device_details': common | {'device': device, 'owner': employee},
        'check_software_entitlement': common | {'employee': employee, 'software': row('software_products', queries.SOFTWARE_COLUMNS),
                                               'entitlement': None, 'license_expired': None},
        'get_recent_support_tickets': common | {'employee': employee, 'tickets': [row('support_tickets', queries.TICKET_COLUMNS)], 'has_more': False},
        'get_active_service_incidents': common | {'service': row('services', queries.SERVICE_COLUMNS),
                                                  'incidents': [row('service_incidents', queries.INCIDENT_COLUMNS)], 'has_more': False},
    }


@pytest.fixture
def inv_dependencies(inv_request, inv_results):
    spec = EmbeddingSpec(provider='fixture', model='fixture-v1', dimensions=3)
    chunks = load_chunks(Path('knowledge_base'))[:3]
    results = [SearchResult(chunk=chunk, distance=i / 4) for i, chunk in enumerate(chunks)]
    return Dependencies(
        classifier=ScriptedClassifier(TicketClassification(category='Network', priority='Medium', summary='VPN connection fails after sign in.')),
        embedder=ScriptedEmbedder(build_query(inv_request.ticket), spec, [1., 0., 0.]),
        store=ReplayStore(spec, results), planner=ScriptedPlanner([{'kind': 'finish'}]),
        fixture_lookup=lambda tool, request: deepcopy(inv_results[tool]),
    )
