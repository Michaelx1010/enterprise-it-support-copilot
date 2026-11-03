"""Small, side-effect-free display projections; no inferred operational conditions."""

from app.investigation.schemas import InvestigationResult, InvestigationSynthesis


def visible_report(result: InvestigationResult) -> InvestigationSynthesis | None:
    # Preserve the underlying result/trace, but never present a failed retrieval's
    # deterministic no-KB text as proof of absent policy or delivered synthesis.
    retrieval_failed = any(error.stage == 'retrieval' for error in result.errors)
    no_kb_fallback = any(event.outcome == 'no_kb_abstention' for event in result.graph_trace)
    return None if retrieval_failed and no_kb_fallback else result.recommendation


def outcome(result: InvestigationResult) -> tuple[str, str]:
    if result.status == 'failed':
        return 'error', 'Investigation failed. No complete recommendation is available.'
    if result.status == 'partial':
        return 'warning', 'Partial investigation. Review the errors and retained evidence before acting.'
    if result.stop_reason == 'clarify':
        return 'info', 'More information needed before investigation can continue.'
    report = visible_report(result)
    if report and report.status == 'insufficient_evidence':
        return 'warning', 'Insufficient evidence for a current action.'
    return 'success', 'Investigation complete. Human review is still required.'


def escalation_label(report: InvestigationSynthesis | None) -> str:
    if report is None or report.status == 'insufficient_evidence':
        return 'Undetermined'
    return 'Handoff recommended' if report.escalation_required else 'No current handoff recommended'


def reference_labels(result: InvestigationResult) -> dict[tuple[str, str], str]:
    labels = {('ticket', ''): 'Ticket report', ('investigation_context', ''): 'Investigation record'}
    labels.update({('kb_chunk', e.reference.chunk_id): f'KB {i}' for i, e in enumerate(result.kb_evidence, 1)})
    labels.update({('operational_observation', e.reference.lookup_id): f'OPS {i}'
                   for i, e in enumerate(result.operational_evidence, 1)})
    return labels


def fact_rows(value: dict, prefix: str = '') -> list[dict[str, str]]:
    """Readable structured facts with all source timestamps, no invented summaries."""
    rows = []
    for key, item in value.items():
        name = f'{prefix} / {key.replace("_", " ")}'.strip(' /')
        if isinstance(item, dict):
            rows.extend(fact_rows(item, name))
        elif isinstance(item, list):
            for index, child in enumerate(item, 1):
                if isinstance(child, dict):
                    rows.extend(fact_rows(child, f'{name} {index}'))
            if not item:
                rows.append({'Recorded field': name, 'Value': 'No records returned'})
        else:
            rows.append({'Recorded field': name, 'Value': 'Not recorded' if item is None else str(item)})
    return rows


def observation_summary(tool: str, data: dict) -> str:
    if data['status'] == 'not_found':
        return 'Requested record not found; this is not proof of an account or service condition.'
    if tool == 'get_employee_account_status':
        account = data.get('account')
        return ('Recorded account: ' + account['account_status'] + '; MFA: ' + account['mfa_status']) if account else 'No account state recorded.'
    if tool == 'get_employee_devices':
        return f'{len(data["devices"])} recorded device(s) for the scoped employee.'
    if tool == 'get_device_details':
        return 'Device inventory returned; current state is unverified.'
    if tool == 'get_active_service_incidents':
        return f'{len(data["incidents"])} incident snapshot(s) matched the query; present activity and causality are unverified.'
    if tool == 'get_recent_support_tickets':
        return f'{len(data["tickets"])} historical ticket(s); prior resolutions do not establish current conditions.'
    return 'Recorded software entitlement returned; this does not authorize an access change.'
