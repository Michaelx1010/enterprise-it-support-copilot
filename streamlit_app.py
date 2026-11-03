"""Local Streamlit entry point. Paid work only occurs on explicit form submission."""

import streamlit as st
from pydantic import ValidationError

from app.demo import service
from app.demo.presentation import (
    escalation_label, fact_rows, observation_summary, outcome, reference_labels, visible_report,
)
from app.investigation.schemas import InvestigationRequest


st.set_page_config(page_title='Northstar | IT Support Copilot', page_icon='◈', layout='wide')
st.markdown('''<style>
    .block-container {max-width: 1180px; padding-top: 2.2rem; padding-bottom: 3rem;}
    [data-testid="stSidebar"] {border-right: 1px solid #DFE7EA;}
    [data-testid="stMetric"] {background: #fff; border: 1px solid #DFE7EA;
        padding: 16px 20px; border-radius: 12px;}
    [data-testid="stMetricValue"] {font-size: 1.55rem;}
    .eyebrow {color: #176B62; font-size: .76rem; letter-spacing: .16em; font-weight: 700;}
    .hero {font-size: 2.45rem; font-weight: 750; letter-spacing: -.04em; line-height: 1.2; margin: .5rem 0;}
    .subhead {color: #516573; max-width: 760px; line-height: 1.6; margin-bottom: 1.8rem;}
    .stTabs [data-baseweb="tab-list"] {gap: 1.4rem;}
</style>''', unsafe_allow_html=True)  # Static styles only; evidence is always plain text.

ERROR_MESSAGES = {
    'live_not_authorized': 'Live execution requires the local opt-in and your paid-use confirmation.',
    'missing_configuration': 'Live configuration is incomplete. Set OPENAI_API_KEY, OPS_DATABASE_URL and KB_READER_DATABASE_URL locally. See docs/demo.md.',
    'invalid_request': 'Check the ticket and scope identifiers. Use EMP-001, SVC-001 or SW-001 formats; lists must contain unique identifiers.',
    'unknown_example': 'This example is unavailable. Select a listed scenario.',
    'investigation_setup_failed': 'The investigation could not start. Check local configuration and connectivity. No connection details are displayed.',
}
FIELD_LABELS = {'employee_id': 'Employee ID', 'service_ids': 'Service IDs',
                'software_ids': 'Software IDs', 'ticket_details': 'Ticket symptoms and completed checks'}
TOOL_LABELS = {
    'get_employee_account_status': 'Check recorded account status',
    'get_employee_devices': 'Find assigned devices',
    'get_device_details': 'Inspect device inventory',
    'check_software_entitlement': 'Check software entitlement',
    'get_recent_support_tickets': 'Read recent support history',
    'get_active_service_incidents': 'Check recorded service incidents',
}


def citations(references, labels):
    names = [labels.get((r.kind, getattr(r, 'chunk_id', getattr(r, 'lookup_id', ''))), 'Unknown reference')
             for r in references]
    st.caption('Sources: ' + ' · '.join(names) + ' — open Evidence to inspect')


def statement(item, labels):
    st.text(item.text)
    citations(item.references, labels)


def render_result(run: service.DemoRun):
    result = run.result
    report = visible_report(result)
    labels = reference_labels(result)
    st.divider()
    st.subheader('Investigation report')
    st.text(run.request.ticket.subject)
    if run.mode == 'example':
        st.info('SCRIPTED EXAMPLE · Authored responses and replayed lookup snapshots. No live model, database search or new operational observations.')
    else:
        st.caption('LIVE WORKFLOW · Model-generated analysis of fictional operational snapshots. Operational state is not verified live.')
    level, message = outcome(result)
    getattr(st, level)(message)
    a, b, c, d = st.columns(4)
    a.metric('Category', result.classification.category if result.classification else 'Unavailable')
    b.metric('Priority', result.classification.priority if result.classification else 'Unavailable')
    c.metric('KB sections', len(result.kb_evidence))
    d.metric('Replayed lookups' if run.mode == 'example' else 'Executed lookups', sum(t.executed for t in result.lookup_trace))

    recommendation, evidence, activity = st.tabs(['Recommendation', 'Evidence', 'Activity & limitations'])
    with recommendation:
        left, right = st.columns([1.8, 1], gap='large')
        with left:
            st.subheader('Summary')
            if report:
                statement(report.summary, labels)
            else:
                st.warning('No accepted recommendation is available. Previously gathered evidence is retained in the Evidence tab.')
                if any(error.stage == 'retrieval' for error in result.errors):
                    st.text('Retrieval failed; this does not establish that the organization lacks a procedure.')
            st.subheader('Current recommended actions')
            st.caption('Proposed for a human to review. No changes or handoffs were executed.')
            if report and report.steps:
                for index, step in enumerate(report.steps, 1):
                    with st.container(border=True):
                        st.caption(f'{index:02d}  ·  ' + ('HUMAN HANDOFF' if step.step_type == 'escalation' else 'TROUBLESHOOTING'))
                        st.text(step.action)
                        citations(step.references, labels)
            else:
                st.text('No current action is recommended from this result.')
            st.subheader('Conditional future guidance')
            st.caption('Only if the documented condition becomes established. These are not current or completed actions.')
            if report and report.conditional_guidance:
                for item in report.conditional_guidance:
                    with st.container(border=True):
                        st.markdown('**If this condition is established**')
                        st.text(item.condition)
                        st.markdown('**Then consider this documented action**')
                        st.text(item.action)
                        st.markdown('**Evidence still needed**')
                        st.text(item.missing_evidence)
                        citations(item.references, labels)
            else:
                st.text('No conditional guidance in this result.')
        with right:
            with st.container(border=True):
                st.markdown('**Current escalation**')
                st.text(escalation_label(report))
                if report and report.escalation_reason:
                    statement(report.escalation_reason, labels)
                if report and report.trigger_basis:
                    st.markdown('**Claimed trigger basis**')
                    st.text(report.trigger_basis.explanation)
                    st.caption('Documented policy')
                    citations(report.trigger_basis.policy_references, labels)
                    st.caption('Reported / recorded trigger facts')
                    citations(report.trigger_basis.factual_references, labels)
                if report is None or report.status == 'insufficient_evidence':
                    st.caption('Undetermined does not mean escalation is unnecessary or the issue is safe.')
            with st.container(border=True):
                st.markdown('**Missing information**')
                missing = report.missing_information if report else []
                for field in result.missing_fields:
                    st.text(FIELD_LABELS.get(field, 'Additional ticket information'))
                for item in missing:
                    st.text(item)
                if not missing and not result.missing_fields:
                    st.caption('No additional information requested in this result.')
            st.warning('Human review required. This is an advisory report, not an approval workflow. Verify source support before acting.')
        if report:
            with st.expander('Findings and uncertainty', expanded=bool(report.uncertainties)):
                for item in report.findings:
                    statement(item, labels)
                for item in report.uncertainties:
                    st.caption('LIMITATION / UNCERTAINTY')
                    statement(item, labels)

    with evidence:
        st.subheader('Ticket report')
        st.caption('User-reported symptoms and completed actions; not independently verified.')
        st.text(run.request.ticket.description)
        st.caption('Scope supplied for this run')
        st.text('Employee: ' + (run.request.employee_id or 'Not supplied') +
                '  ·  Services: ' + (', '.join(run.request.service_ids) or 'Not supplied') +
                '  ·  Software: ' + (', '.join(run.request.software_ids) or 'Not supplied'))
        st.subheader('Documented procedures')
        st.caption('Citations identify sources. Valid IDs alone do not prove that a claim follows from the text.')
        if not result.kb_evidence:
            st.text('No KB evidence was retained for this run.')
        for index, item in enumerate(result.kb_evidence, 1):
            chunk = item.result.chunk
            with st.expander(f'KB {index} · {chunk.title} / {chunk.section_path}', expanded=True):
                st.text(chunk.content)
                st.caption('Source: ' + chunk.source_path + ' · Section: ' + chunk.section_path)
                st.caption('Chunk ID: ' + chunk.chunk_id)
                st.caption('Scripted selection; no similarity score measured.' if run.mode == 'example'
                           else f'Cosine distance: {item.result.distance:.4f} · No relevance threshold applied.')
        st.subheader('Synthetic operational snapshots')
        st.caption('Read-only observations, not documented policy or verified present conditions. Original timestamps are preserved.')
        if not result.operational_evidence:
            st.text('No operational observations were collected.')
        for index, item in enumerate(result.operational_evidence, 1):
            data = item.observation.result.model_dump(mode='json')
            with st.expander(f'OPS {index} · {TOOL_LABELS[item.observation.tool]}', expanded=False):
                st.text(observation_summary(item.observation.tool, data))
                st.caption('Source query timestamp: ' + data['queried_at'] + ' · Live verified: false')
                st.table(fact_rows(data))

    with activity:
        st.subheader('Read-only lookup sequence')
        st.caption('Example lookups replay recorded fixtures.' if run.mode == 'example' else 'Only validated, scoped read-only tools may execute.')
        if not result.lookup_trace:
            st.text('No lookups executed.')
        for index, item in enumerate(result.lookup_trace, 1):
            with st.container(border=True):
                st.markdown(f'**{index:02d} · {TOOL_LABELS.get(item.tool, "Blocked tool request")}**')
                st.text(('Replayed' if run.mode == 'example' else 'Executed') if item.executed else 'Not executed')
                st.caption('Outcome: ' + item.status + ((' · ' + item.code) if item.code else ''))
                if item.arguments:
                    st.text('Scope: ' + ', '.join(f'{key}={value}' for key, value in item.arguments.items()))
        st.subheader('Run record')
        st.caption(f'Planner decisions attempted: {result.planner_decisions}/4 · Lookup attempts: {result.lookup_attempts}/4')
        st.caption('Synthesis: ' + result.synthesis_status + ' · Provider attempts: ' + str(result.synthesis_attempts) +
                   (' (scripted, zero API calls)' if run.mode == 'example' else ' (zero may indicate a deterministic abstention)'))
        st.caption('Run started: ' + result.started_at.isoformat() + ' · Finished: ' + result.finished_at.isoformat())
        st.caption('Stop reason: ' + result.stop_reason)
        st.text('Mutating actions executed: none. Account changes, approvals and escalations are never performed.')
        if result.errors:
            st.error('Some stages failed. Safe error codes are listed below; raw provider and connection details are withheld.')
            st.table([error.model_dump() for error in result.errors])
        with st.expander('Graph trace'):
            st.table([event.model_dump() for event in result.graph_trace])
        st.caption('A completed workflow or accepted schema is not a semantic quality score. Human review remains necessary.')


def main():
    with st.sidebar:
        st.markdown('### ◈ NORTHSTAR')
        st.caption('ENTERPRISE IT SUPPORT COPILOT')
        st.divider()
        mode = st.radio('Investigation mode', ['Scripted examples', 'Live investigation'], key='mode')
        cases = service.examples()
        selected = st.selectbox('Fictional scenario', [case['id'] for case in cases],
                                format_func=lambda key: next(case['title'] for case in cases if case['id'] == key),
                                disabled=mode != 'Scripted examples', key='scenario')
        st.divider()
        st.markdown('**Evidence before action**')
        st.caption('Ticket → classification → KB retrieval → bounded investigation → grounded report')
        st.caption('6 read-only tools · up to 4 planner decisions · human review required')
        with st.expander('About this portfolio demo'):
            st.write('Python · Pydantic · PostgreSQL/pgvector · LangGraph · OpenAI Structured Outputs')
            st.write('Example mode runs the real graph with scripted providers. Live mode uses restricted database readers and the existing model providers.')
            st.caption('Local, single-user demonstration. All company records are fictional. See docs/demo.md for setup and limitations.')
    context = (mode, selected)
    if st.session_state.get('context') != context:
        st.session_state.pop('run', None)
        st.session_state['context'] = context
    st.markdown('<div class="eyebrow">ENTERPRISE IT SUPPORT COPILOT</div><div class="hero">From ticket to a grounded next step.</div><div class="subhead">Investigate a support request, inspect the evidence, and understand what a human should do next.</div>', unsafe_allow_html=True)
    if mode == 'Scripted examples':
        case = next(case for case in cases if case['id'] == selected)
        st.caption('NO-COST DEMO · No API key or database required')
        st.text(case['description'])
        with st.form('example_form'):
            st.markdown('**Ticket subject**')
            st.text(case['request']['ticket']['subject'])
            st.markdown('**Description**')
            st.text(case['request']['ticket']['description'])
            st.caption('Fixed fictional input and authored output. Switch to live mode to investigate your own fictional ticket.')
            submitted = st.form_submit_button('Run investigation', type='primary')
        if submitted:
            st.session_state.pop('run', None)
            with st.spinner('Replaying the investigation graph locally…'):
                st.session_state['run'] = service.run_example(selected)
    else:
        enabled = service.live_enabled()
        st.warning('Live mode sends the ticket and relevant fictional evidence to OpenAI and may incur API charges. Use fictional inputs only; never enter credentials.')
        if not enabled:
            st.info('Live execution is disabled. Start with IT_SUPPORT_DEMO_LIVE=1 and the existing local environment files; see docs/demo.md.')
        with st.form('live_form'):
            subject = st.text_input('Ticket subject', max_chars=200, key='subject')
            description = st.text_area('Description', height=140, max_chars=3500, key='description',
                                       placeholder='Describe the symptoms, checks already completed and their outcomes.')
            a, b, c = st.columns(3)
            employee = a.text_input('Employee ID (optional)', placeholder='EMP-001', max_chars=7)
            services = b.text_input('Service IDs (optional)', placeholder='SVC-001, SVC-002', max_chars=70)
            software = c.text_input('Software IDs (optional)', placeholder='SW-001', max_chars=70)
            st.caption('Supply identifiers only when relevant. The application cannot expand scope to unrelated employees.')
            consent = st.checkbox('I authorize paid API calls for this investigation.', key='paid_consent')
            submitted = st.form_submit_button('Run investigation', type='primary', disabled=not enabled)
        if submitted:
            st.session_state.pop('run', None)
            try:
                request = InvestigationRequest(ticket={'subject': subject, 'description': description},
                    employee_id=employee.strip() or None,
                    service_ids=[x.strip() for x in services.split(',') if x.strip()],
                    software_ids=[x.strip() for x in software.split(',') if x.strip()])
                with st.spinner('Investigating with the existing read-only workflow… This can take up to a few minutes.'):
                    st.session_state['run'] = service.run_live(request, allow_paid=consent)
            except ValidationError:
                st.error(ERROR_MESSAGES['invalid_request'])
            except service.DemoError as exc:
                st.error(ERROR_MESSAGES.get(str(exc), ERROR_MESSAGES['investigation_setup_failed']))
    if 'run' in st.session_state:
        render_result(st.session_state['run'])
    else:
        st.caption('Run an investigation to see recommendations, source evidence and the lookup sequence here.')


try:
    main()
except Exception:
    # Do not render arbitrary exceptions, validation inputs or environment values.
    st.error('The demo could not render this run. Check the local setup; no diagnostic payloads are displayed.')
