"""Queue and restart mechanics use isolated synthetic SQL, never real user data."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from gianna.db import IntegrityError, dumps
from gianna.errors import DomainError, Cancelled
from gianna.services.jobs import Jobs
from gianna.services.settings import Settings


@pytest.fixture
def queue(db, cfg):
    engine = SimpleNamespace(load=lambda: None, profile={'test': True})
    return Jobs(db, cfg, SimpleNamespace(active=lambda: None), engine, None)


@pytest.mark.parametrize('payload', ['{', '[]', 'null', '"private-content"'])
def test_malformed_payload_is_terminal_and_does_not_hold_queue(queue, payload):
    identifier = queue.enqueue('warmup')
    next_id = queue.enqueue('warmup')
    queue.db.execute('UPDATE jobs SET payload_json=? WHERE id=?', (payload, identifier))
    queue.execute_job(queue.claim())
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'failed' and row['error_code'] == 'invalid_job_payload'
    assert row['owner_token'] is None and row['lease_until'] is None
    assert payload not in (row['error'] or '')
    assert queue.claim()['id'] == next_id


@pytest.mark.parametrize('code', ['storage_not_mounted', 'storage_mismatch', 'snapshot_invalid', 'embedding_mismatch'])
def test_permanent_failure_explains_action_without_blind_retry(queue, code):
    def fail(*args, **kwargs):
        raise DomainError('Una dependencia requiere revisión.', 503, code)
    queue.rag = SimpleNamespace(recovery=SimpleNamespace(recover=fail))
    identifier = queue.enqueue('warmup')
    queue.execute_job(queue.claim())
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'failed' and row['attempts'] == 1
    stage = 'storage' if code.startswith('storage_') else 'snapshot' if code == 'snapshot_invalid' else 'profile'
    assert row['error_code'] == code and row['error_stage'] == stage
    assert row['action'] and not row['retryable']
    assert queue.claim() is None
    events = queue.describe_job(identifier)['events']
    assert events[0]['code'] == code and events[0]['message']


def test_transient_retry_has_eta_bounded_attempts_and_persistent_history(queue):
    def offline(*args, **kwargs):
        raise DomainError('El hub no está disponible.', 503, 'models_recovery_failed')
    queue.rag = SimpleNamespace(recovery=SimpleNamespace(recover=offline))
    identifier = queue.enqueue('warmup')
    for attempt in range(1, 4):
        queue.execute_job(queue.claim())
        row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
        assert row['attempts'] == attempt
        assert row['owner_token'] is None and row['lease_until'] is None
        assert row['error_code'] == 'models_recovery_failed'
        if attempt < 3:
            assert row['status'] == 'queued' and row['error'] is None and row['finished_at'] is None
            assert row['available_at'] > time.time() and queue.claim() is None
            assert queue.describe_job(identifier)['retry_in_seconds'] > 0
            queue.db.execute('UPDATE jobs SET available_at=0 WHERE id=?', (identifier,))
        else:
            assert row['status'] == 'failed' and row['finished_at']
    assert queue.db.one("SELECT COUNT(*) n FROM job_events WHERE job_id=? AND event='job_attempt_failed'", (identifier,))['n'] == 3
    assert queue.db.one("SELECT COUNT(*) n FROM operational_events WHERE job_id=? AND event='queue.retry_scheduled'", (identifier,))['n'] == 2


def test_claim_clears_old_attempt_metadata(queue):
    identifier = queue.enqueue('warmup')
    queue.db.execute("UPDATE jobs SET error='old',error_code='old',error_stage='old',action='old',retryable=1,finished_at=1,result_json='{}' WHERE id=?", (identifier,))
    claimed = queue.claim()
    for key in ('error', 'error_code', 'error_stage', 'action', 'finished_at', 'result_json'):
        assert claimed[key] is None
    assert claimed['heartbeat_at'] and claimed['last_attempt_at'] and claimed['boot_id']
    assert claimed['stage'] == 'validate_payload' and claimed['retryable'] == 0


@pytest.mark.parametrize('kind', ['warmup', 'import', 'build', 'delete', 'evaluation'])
def test_interruption_limit_applies_to_every_job_kind(queue, kind):
    identifier = queue.enqueue('warmup')
    queue.db.execute('UPDATE jobs SET kind=?,attempts=2 WHERE id=?', (kind, identifier))
    queue.claim()
    queue.db.execute('UPDATE jobs SET lease_until=NULL WHERE id=?', (identifier,))
    assert queue.claim() is None
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'failed' and row['error_code'] == 'job_interrupted'
    assert row['finished_at'] and row['owner_token'] is None


def test_lost_owner_cannot_modify_reclaimed_job(queue, cfg):
    identifier = queue.enqueue('warmup')
    stale = queue.claim()
    queue.db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (identifier,))
    new = Jobs(queue.db, cfg, queue.knowledge, queue.embeddings, None)
    replacement = new.claim()
    assert replacement['id'] == identifier and replacement['owner_token'] != stale['owner_token']
    with pytest.raises(Cancelled):
        queue.progress(identifier, 'old owner update', 99, 99)
    with pytest.raises(Cancelled):
        queue._complete(stale, {'invalid': True})
    queue.execute_job(stale)
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'running' and row['owner_token'] == new.token
    assert row['progress'] == 0 and row['attempts'] == 2


def test_queue_cancel_is_immediate_even_when_installation_is_blocked(queue):
    identifier = queue.enqueue('warmup')
    queue._phase = 'blocked'
    queue.cancel(identifier)
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'cancelled' and row['cancel_requested'] == 1
    assert queue.claim() is None


def test_requested_cancellation_survives_lease_reclaim(queue):
    identifier = queue.enqueue('warmup')
    queue.claim()
    queue.cancel(identifier)
    queue.db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (identifier,))
    assert queue.claim() is None
    assert queue.db.one('SELECT status FROM jobs WHERE id=?', (identifier,))['status'] == 'cancelled'


def test_manual_retry_keeps_job_and_attempt_history(queue):
    identifier = queue.enqueue('warmup')
    queue.db.execute("UPDATE jobs SET payload_json='[',status='failed',attempts=3,error='old',error_code='old' WHERE id=?", (identifier,))
    queue.retry(identifier)
    row = queue.db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['id'] == identifier and row['attempts'] == 0 and row['status'] == 'queued'
    assert row['payload_json'] == '['  # No invented replacement payload.
    assert row['error'] is None and row['finished_at'] is None
    assert queue.describe_job(identifier)['events'][0]['event'] == 'job_retry_requested'


def test_blocked_preflight_never_claims_pending_work(queue, monkeypatch):
    identifier = queue.enqueue('warmup')
    queue.installation = SimpleNamespace(reconcile=lambda: {'state': 'blocked', 'code': 'storage_not_mounted', 'message': 'Revisá almacenamiento'})
    monkeypatch.setattr(queue, 'claim', lambda: pytest.fail('Blocked installation claimed work'))
    monkeypatch.setattr(queue, '_wait', lambda seconds: queue.stop_event.set())
    queue.run()
    assert queue.db.one('SELECT attempts,status FROM jobs WHERE id=?', (identifier,)) == {'attempts': 0, 'status': 'queued'}
    assert queue.status()['last_error']['code'] == 'storage_not_mounted'


def test_start_does_not_read_database_on_the_callers_thread(queue, monkeypatch):
    caller = threading.current_thread()
    real_execute = queue.db.execute
    def checked_execute(*args, **kwargs):
        assert threading.current_thread() is not caller
        return real_execute(*args, **kwargs)
    monkeypatch.setattr(queue.db, 'execute', checked_execute)
    queue.installation = SimpleNamespace(reconcile=lambda: {'state': 'blocked', 'code': 'test_dependency'})
    monkeypatch.setattr(queue, '_wait', lambda seconds: queue.stop_event.set())
    queue.start()
    queue.thread.join(2)
    assert not queue.thread.is_alive() and queue._last_error['code'] == 'test_dependency'


def test_unavailable_sql_has_bounded_worker_backoff(queue, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError('Synthetic outage')
    waits = []
    monkeypatch.setattr(queue.db, 'tx', unavailable)
    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            queue.stop_event.set()
    monkeypatch.setattr(queue, '_wait', wait)
    queue.run()
    assert waits == [1, 2, 4]
    assert queue._last_error['code'] == 'network_unavailable'


def test_repaired_preflight_resumes_existing_warmup_once_per_boot(db, cfg, knowledge, corpus):
    base = knowledge.import_corpus(corpus, 'Synthetic', 'actor')
    knowledge.approve_public(base, 'actor')
    identifier, version = knowledge.enqueue_build(base, Settings(), 'actor')
    db.execute("UPDATE jobs SET kind='warmup',payload_json=?,status='failed',attempts=3,error_code='storage_not_mounted' WHERE id=?", (dumps({'version_id': version}), identifier))
    before = db.all('SELECT * FROM versions')
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs._resume_environment_jobs()
    row = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'queued' and row['attempts'] == 0
    assert row['version_id'] == version and row['recovery_boot_id'] == jobs.boot_id
    assert db.all('SELECT * FROM versions') == before
    db.execute("UPDATE jobs SET status='failed',attempts=3,error_code='storage_not_mounted' WHERE id=?", (identifier,))
    jobs._boot_reconciled = False
    jobs._resume_environment_jobs()
    assert db.one('SELECT status,attempts FROM jobs WHERE id=?', (identifier,)) == {'status': 'failed', 'attempts': 3}
    db.execute("UPDATE jobs SET status='cancelled',cancel_requested=1 WHERE id=?", (identifier,))
    jobs.boot_id = 'new-process-boot'
    jobs._boot_reconciled = False
    jobs._resume_environment_jobs()
    assert db.one('SELECT status FROM jobs WHERE id=?', (identifier,))['status'] == 'cancelled'


def test_public_job_description_omits_owner_and_payload(queue):
    identifier = queue.enqueue('warmup', {'private': 'not-in-response'})
    queue.claim()
    result = queue.describe_job(identifier)
    encoded = json.dumps(result)
    assert 'owner_token' not in encoded and 'payload_json' not in encoded
    assert 'not-in-response' not in encoded and queue.token not in encoded
    assert result['attempts'] == 1 and result['max_attempts'] == 3


def test_failure_policy_uses_specific_sanitized_action_and_retry_decision(queue):
    def fail(*args, **kwargs):
        error = DomainError('No se pudo inspeccionar almacenamiento.', 503, 'storage_permission_denied')
        error.details = {'action': 'Revisá UID 10001; password=never-show-this', 'retryable': False}
        raise error
    queue.rag = SimpleNamespace(recovery=SimpleNamespace(recover=fail))
    identifier = queue.enqueue('warmup')
    queue.execute_job(queue.claim())
    result = queue.describe_job(identifier)
    assert result['error_stage'] == 'storage' and result['status'] == 'failed'
    assert 'UID 10001' in result['action'] and 'never-show-this' not in json.dumps(result)


def test_lost_import_ownership_does_not_remove_the_uploaded_source(db, cfg, knowledge, corpus, monkeypatch):
    upload = cfg.data_dir/'uploads'/'synthetic.json'
    upload.write_text(corpus.model_dump_json(), encoding='utf8')
    engine = SimpleNamespace(load=lambda: None, profile={})
    jobs = Jobs(db, cfg, knowledge, engine, None)
    identifier = jobs.enqueue('import', {'path': str(upload)})
    original = knowledge.import_corpus
    def imported_then_reclaimed(*args, **kwargs):
        result = original(*args, **kwargs)
        db.execute("UPDATE jobs SET owner_token='replacement-owner' WHERE id=?", (identifier,))
        return result
    monkeypatch.setattr(knowledge, 'import_corpus', imported_then_reclaimed)
    jobs.execute_job(jobs.claim())
    assert upload.is_file()
    row = db.one('SELECT status,owner_token FROM jobs WHERE id=?', (identifier,))
    assert row == {'status': 'running', 'owner_token': 'replacement-owner'}


def test_already_published_snapshot_is_never_rebuilt(db, cfg, knowledge, corpus):
    base = knowledge.import_corpus(corpus, 'Synthetic', 'actor')
    knowledge.approve_public(base, 'actor')
    identifier, version = knowledge.enqueue_build(base, Settings(), 'actor')
    db.execute("UPDATE versions SET status='ready',published_at=1 WHERE id=?", (version,))
    before = db.one('SELECT * FROM versions WHERE id=?', (version,))
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.execute_job(jobs.claim())
    assert db.one('SELECT * FROM versions WHERE id=?', (version,)) == before
    assert db.one('SELECT error_code FROM jobs WHERE id=?', (identifier,))['error_code'] == 'published_version_protected'


def test_new_version_is_not_ready_before_its_integrity_gate(db, cfg, knowledge, corpus):
    from fakes import MechanicalJobs, FakeEmbeddings, FakeLanceStore
    base = knowledge.import_corpus(corpus, 'Synthetic', 'actor')
    knowledge.approve_public(base, 'actor')
    identifier, version = knowledge.enqueue_build(base, Settings(), 'actor')
    observed = []
    def reject(candidate):
        observed.append(db.one('SELECT status FROM versions WHERE id=?', (version,))['status'])
        assert candidate['status'] == 'ready'
        raise DomainError('La verificación física detectó un problema.', 503, 'index_integrity_failed')
    rag = SimpleNamespace(recovery=SimpleNamespace(verify=reject))
    jobs = MechanicalJobs(db, cfg, knowledge, FakeEmbeddings(), FakeLanceStore(), rag)
    jobs.execute_job(jobs.claim())
    assert observed == ['building']
    assert db.one('SELECT status FROM versions WHERE id=?', (version,))['status'] == 'failed'
    assert knowledge.active() is None


def test_later_explicit_cancel_prevents_resurrecting_older_failed_warmup(db, cfg, knowledge, corpus):
    base = knowledge.import_corpus(corpus, 'Synthetic', 'actor')
    knowledge.approve_public(base, 'actor')
    identifier, version = knowledge.enqueue_build(base, Settings(), 'actor')
    db.execute("UPDATE jobs SET kind='warmup',status='failed',error_code='storage_not_mounted' WHERE id=?", (identifier,))
    jobs = Jobs(db, cfg, knowledge, None, None)
    later = jobs.enqueue('warmup', {'version_id': version}, version_id=version)
    jobs.cancel(later)
    jobs._resume_environment_jobs()
    assert db.one('SELECT status FROM jobs WHERE id=?', (identifier,))['status'] == 'failed'
    assert db.one('SELECT status FROM jobs WHERE id=?', (later,))['status'] == 'cancelled'


def test_missing_history_schema_does_not_prevent_reading_an_existing_job(queue):
    identifier = queue.enqueue('warmup')
    queue.db.execute('DROP TABLE job_events')
    description = queue.describe_job(identifier)
    assert description['id'] == identifier and description['status'] == 'queued'
    assert description['history_available'] is False and description['events'] == []


def test_legacy_queued_cancel_wins_over_backoff_and_attempt_exhaustion(queue):
    identifier = queue.enqueue('warmup')
    queue.db.execute('UPDATE jobs SET cancel_requested=1,attempts=3,available_at=? WHERE id=?', (time.time()+9999, identifier))
    assert queue.claim() is None
    assert queue.db.one('SELECT status FROM jobs WHERE id=?', (identifier,))['status'] == 'cancelled'


@pytest.mark.parametrize('number,code', [
    (1364, 'database_schema_incompatible'), (1054, 'database_schema_incompatible'),
    (1146, 'database_schema_incompatible'), (1062, 'database_constraint_violation'),
    (1452, 'database_constraint_violation'), (None, 'database_constraint_violation'),
])
def test_integrity_error_reports_safe_type_and_action_without_sql_values(queue, number, code):
    class DriverFailure(Exception):
        errno = number
    def fail(*args, **kwargs):
        try:
            raise DriverFailure('Private document, SELECT internal_value FROM private_data')
        except DriverFailure as driver:
            raise IntegrityError('password=must-not-leak; private-record-id') from driver
    queue.rag = SimpleNamespace(recovery=SimpleNamespace(recover=fail))
    identifier = queue.enqueue('warmup')
    queue.execute_job(queue.claim())
    result = queue.describe_job(identifier)
    assert result['error_code'] == code and 'IntegrityError' in result['error']
    assert not result['retryable'] and result['status'] == 'failed' and result['action']
    journal = queue.db.all('SELECT event,level,details_json FROM operational_events WHERE job_id=?', (identifier,))
    assert any(row['event'] == 'queue.failed' and row['level'] == 'error' for row in journal)
    serialized = json.dumps(result) + json.dumps(journal)
    assert 'must-not-leak' not in serialized and 'private-record-id' not in serialized
    assert 'Private document' not in serialized and 'SELECT internal_value' not in serialized


def test_retry_event_is_warning_and_stage_changes_are_info(queue):
    def offline(*args, **kwargs):
        raise DomainError('Una dependencia no está disponible.', 503, 'models_recovery_failed')
    queue.rag = SimpleNamespace(recovery=SimpleNamespace(recover=offline))
    identifier = queue.enqueue('warmup')
    queue.execute_job(queue.claim())
    events = queue.db.all('SELECT event,level FROM operational_events WHERE job_id=?', (identifier,))
    assert {'event': 'queue.retry_scheduled', 'level': 'warning'} in events
    assert {'event': 'job.stage_changed', 'level': 'info'} in events


def failed_publication(db, knowledge, corpus, *, name='Synthetic publication'):
    """Synthetic metadata fixture: these tests cover rescheduling, not RAG quality."""
    base = knowledge.import_corpus(corpus, name, 'actor')
    knowledge.approve_public(base, 'actor')
    identifier, version = knowledge.enqueue_build(base, Settings(), 'actor')
    db.execute("UPDATE jobs SET kind='warmup',payload_json=?,status='failed',attempts=3,error='Unknown earlier failure',error_code=NULL WHERE id=?",
               (dumps({'version_id': version}), identifier))
    db.execute("UPDATE versions SET status='ready',published_at=1 WHERE id=?", (version,))
    db.execute('UPDATE active_knowledge SET version_id=? WHERE singleton=1', (version,))
    return identifier, version


def verified_publication_report(version, *, report_id=None):
    return {'report_id': report_id or 'inventory-'+version, 'state': 'recoverable',
            'database': {'active_version_id': version}, 'storage': {'ok': True},
            'checks': [{'name': 'snapshot', 'status': 'ok', 'details': {'version_id': version}}],
            'plan': [{'action': 'verify_runtime', 'automatic': True}]}


def test_verified_publication_resumes_unknown_legacy_failure_without_rewriting_data(db, cfg, knowledge, corpus):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    report = verified_publication_report(version)
    jobs.installation = SimpleNamespace(reconcile=lambda: report)
    before = {table: db.all('SELECT * FROM '+table) for table in ('versions', 'version_records', 'version_sources', 'active_knowledge', 'chunks')}
    jobs._resume_environment_jobs(report)
    row = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'queued' and row['attempts'] == 0
    assert row['payload_json'] == dumps({'version_id': version})
    assert row['recovery_boot_id'] == jobs.boot_id
    assert {table: db.all('SELECT * FROM '+table) for table in before} == before
    db.execute("UPDATE jobs SET status='failed',attempts=3,error_code='new_unclassified_failure' WHERE id=?", (identifier,))
    jobs._resume_environment_jobs(verified_publication_report(version, report_id='new-inventory-same-boot'))
    assert db.one('SELECT status,attempts FROM jobs WHERE id=?', (identifier,)) == {'status': 'failed', 'attempts': 3}


@pytest.mark.parametrize('invalid_proof', ['blocked', 'snapshot_missing', 'snapshot_other_version',
                                          'runtime_not_automatic', 'storage_blocked', 'active_mismatch'])
def test_unknown_legacy_failure_requires_explicit_matching_publication_proof(db, cfg, knowledge, corpus, invalid_proof):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    report = verified_publication_report(version)
    if invalid_proof == 'blocked':
        report['state'] = 'blocked'
    elif invalid_proof == 'snapshot_missing':
        report['checks'] = []
    elif invalid_proof == 'snapshot_other_version':
        report['checks'][0]['details']['version_id'] = 'another-version'
    elif invalid_proof == 'runtime_not_automatic':
        report['plan'][0]['automatic'] = False
    elif invalid_proof == 'storage_blocked':
        report['storage']['ok'] = False
    elif invalid_proof == 'active_mismatch':
        db.execute('UPDATE active_knowledge SET version_id=NULL WHERE singleton=1')
    before = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    jobs._resume_environment_jobs(report)
    assert db.one('SELECT * FROM jobs WHERE id=?', (identifier,)) == before


@pytest.mark.parametrize('cancelled', ['status', 'flag', 'later_request'])
def test_verified_publication_preserves_explicit_cancellations(db, cfg, knowledge, corpus, cancelled):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    if cancelled == 'status':
        db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (identifier,))
    elif cancelled == 'flag':
        db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?', (identifier,))
    else:
        later = jobs.enqueue('warmup', {'version_id': version}, version_id=version)
        jobs.cancel(later)
    before = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    jobs._resume_environment_jobs(verified_publication_report(version))
    assert db.one('SELECT * FROM jobs WHERE id=?', (identifier,)) == before


@pytest.mark.parametrize('payload', ['{', '[]', '{"version_id":"wrong-version"}'])
def test_publication_proof_does_not_reconstruct_a_corrupt_or_conflicting_payload(db, cfg, knowledge, corpus, payload):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    db.execute('UPDATE jobs SET payload_json=? WHERE id=?', (payload, identifier))
    jobs._resume_environment_jobs(verified_publication_report(version))
    row = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'failed' and row['attempts'] == 3
    assert row['error_code'] == 'invalid_job_payload' and row['action']
    assert row['payload_json'] == payload and row['recovery_boot_id'] is None


def test_publication_proof_accepts_legacy_null_column_only_with_explicit_payload_target(db, cfg, knowledge, corpus):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    db.execute('UPDATE jobs SET version_id=NULL WHERE id=?', (identifier,))
    jobs._resume_environment_jobs(verified_publication_report(version))
    row = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'queued' and row['version_id'] is None
    assert row['payload_json'] == dumps({'version_id': version})


def test_job_without_verifiable_target_remains_failed_with_action(db, cfg, knowledge, corpus):
    identifier, version = failed_publication(db, knowledge, corpus)
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    db.execute("UPDATE jobs SET version_id=NULL,payload_json='{}' WHERE id=?", (identifier,))
    jobs._resume_environment_jobs(verified_publication_report(version))
    row = db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    assert row['status'] == 'failed' and row['payload_json'] == '{}'
    assert row['error_code'] == 'job_target_unverified' and row['action']


def test_new_active_publication_can_resume_its_own_failed_job_in_the_same_boot(db, cfg, knowledge, corpus):
    older, old_version = failed_publication(db, knowledge, corpus, name='Old publication')
    current, current_version = failed_publication(db, knowledge, corpus, name='Current publication')
    jobs = Jobs(db, cfg, knowledge, None, None)
    jobs.installation = SimpleNamespace()
    jobs._boot_reconciled = True  # A global first-boot pass must not suppress it.
    jobs._resume_environment_jobs(verified_publication_report(current_version))
    assert db.one('SELECT status FROM jobs WHERE id=?', (current,))['status'] == 'queued'
    assert db.one('SELECT status FROM jobs WHERE id=?', (older,))['status'] == 'failed'
    # Revisit an earlier publication using a new inventory in the same process.
    db.execute('UPDATE active_knowledge SET version_id=? WHERE singleton=1', (old_version,))
    jobs._resume_environment_jobs(verified_publication_report(old_version))
    assert db.one('SELECT status FROM jobs WHERE id=?', (older,))['status'] == 'queued'
