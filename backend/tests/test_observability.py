"""Operational evidence stays actionable without logging application content."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from types import SimpleNamespace

import httpx

from gianna.errors import DomainError
from gianna.observability import (
    bind_context, boot_id, configure_logging, event, safe_exception,
    sanitize_fields, current_context, StructuredFormatter,
)


LOG = logging.getLogger('gianna.tests.observability')


def emitted(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith('{')]


def test_configuration_preserves_capture_and_does_not_duplicate_handlers(caplog, capsys):
    root = logging.getLogger()
    existing = list(root.handlers)
    configure_logging()
    handlers = list(root.handlers)
    configure_logging()
    assert root.handlers == handlers
    assert all(handler in root.handlers for handler in existing)
    with caplog.at_level(logging.INFO, logger='gianna'):
        event(LOG, 'queue.started', pending_jobs=2)
    rows = [row for row in emitted(capsys) if row['event'] == 'queue.started']
    assert len(rows) == 1
    assert 'queue.started' in caplog.text
    assert rows[0]['fields'] == {'pending_jobs': 2}
    assert rows[0]['boot_id'] == boot_id()
    assert rows[0]['time'].endswith('Z') and rows[0]['level'] == 'INFO'


def test_context_is_nested_reset_and_isolated_between_worker_threads(capsys):
    configure_logging()
    with bind_context(request_id='request-a'):
        with bind_context(job_id='job-a', attempt=2):
            event(LOG, 'job.stage', stage='checking_storage')
        event(LOG, 'request.finished', duration_ms=12)
    event(LOG, 'outside.context')
    def worker(index):
        with bind_context(job_id=f'job-{index}'):
            event(LOG, 'thread.stage', attempt=index)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))
    rows = emitted(capsys)
    stage = next(row for row in rows if row['event'] == 'job.stage')
    assert stage['fields'] == {'request_id':'request-a', 'job_id':'job-a', 'attempt':2, 'stage':'checking_storage'}
    finished = next(row for row in rows if row['event'] == 'request.finished')
    assert finished['fields'] == {'request_id':'request-a', 'duration_ms':12}
    assert next(row for row in rows if row['event'] == 'outside.context')['fields'] == {}
    threaded = [row for row in rows if row['event'] == 'thread.stage']
    assert {row['fields']['job_id'] for row in threaded} == {'job-0', 'job-1'}
    assert all('request_id' not in row['fields'] for row in threaded)


def test_exception_chain_retains_types_codes_and_locations_without_values():
    confidential = 'private-request-body-never-log'
    try:
        try:
            raise OSError(28, confidential, '/private/' + confidential)
        except OSError as cause:
            raise DomainError('SELECT secret FROM accounts ' + confidential, 503, 'storage_write_failed') from cause
    except DomainError as exc:
        result = safe_exception(exc)
    rendered = json.dumps(result)
    assert confidential not in rendered and 'SELECT' not in rendered
    assert result['type'] == 'DomainError'
    assert result['code'] == 'storage_write_failed' and result['http_status'] == 503
    assert result['causes'][0]['type'] == 'OSError' and result['causes'][0]['errno'] == 28
    assert result['frames'][-1]['function'] == 'test_exception_chain_retains_types_codes_and_locations_without_values'
    assert result['frames'][-1]['file'] == 'test_observability.py'
    assert result['frames'][-1]['line'] > 0
    assert all('message' not in cause for cause in result['causes'])


def test_metadata_redaction_is_shared_with_persisted_journal_and_bounded():
    payload = sanitize_fields({
        'job_id':'job-ok', 'duration_ms':2.4, 'attempt':3,
        'password':'private-credential', 'message':'private-log-message',
        'body':{'records':['private-record']}, 'query':'private-query',
        'details':{'headers':{'Authorization':'Bearer hidden'}, 'access_token':'hidden'},
        'provider_url':'https://user:private-password@example.test/api?token=hidden#secret',
        'untrusted':object(), 'bad_number':float('nan'), 'many':list(range(100)),
        'source_counts':{'sql':3}, 'prompt_tokens':120, 'content_matches':False,
    })
    serialized = json.dumps(payload, allow_nan=False)
    for secret in ('private-credential','private-log-message','private-record','private-query','private-password','token=hidden','Bearer hidden'):
        assert secret not in serialized
    assert payload['job_id'] == 'job-ok' and payload['duration_ms'] == 2.4
    assert payload['untrusted'] == {'type':'object'} and payload['bad_number'] is None
    assert len(payload['many']) == 40
    assert payload['source_counts']['sql'] == 3 and payload['prompt_tokens'] == 120
    assert payload['content_matches'] is False


def test_legacy_and_third_party_exception_logs_cannot_dump_parameters(caplog, capsys):
    secret = 'sensitive-config-key-for-redaction'
    configure_logging(SimpleNamespace(secret_key=secret))
    with caplog.at_level(logging.INFO):
        LOG.warning('Configured key: %s', secret)
        LOG.warning('SELECT password FROM users WHERE secret = %s', 'private-sql-parameter')
        try:
            raise RuntimeError('private-response-body ' + secret)
        except RuntimeError:
            logging.getLogger('httpx').exception('Provider body: %s', 'private-prompt-text')
    rows = emitted(capsys)
    output = json.dumps(rows) + caplog.text
    for private in (secret,'private-sql-parameter','private-response-body','private-prompt-text'):
        assert private not in output
    external = next(row for row in rows if row['logger'] == 'httpx')
    assert external['exception']['type'] == 'RuntimeError'
    assert external['exception']['frames'][-1]['line'] > 0


def test_legacy_log_credentials_headers_and_relative_url_queries_are_redacted(capsys):
    configure_logging()
    LOG.warning('Connection https://user:private-pass@db.example.test/path?secret=private-query')
    LOG.warning('Authorization: Bearer private-bearer')
    LOG.warning('Cookie: session=private-cookie')
    LOG.warning('Request /admin/login?token=private-token')
    LOG.warning('Email private-person@example.test password=private-password')
    output = json.dumps(emitted(capsys))
    for fragment in ('private-pass','private-query','private-bearer','private-cookie','private-token','private-person','private-password'):
        assert fragment not in output


def test_formatter_omits_external_unstructured_payload_even_without_configuration():
    record = logging.LogRecord('external.driver', logging.ERROR, __file__, 1,
                               'private-free-form-payload', (), None)
    assert 'private-free-form-payload' not in StructuredFormatter().format(record)


def test_logging_uses_current_capture_stream_and_keeps_existing_handlers(monkeypatch):
    configure_logging()
    for _ in range(2):
        stream = io.StringIO()
        with monkeypatch.context() as patch:
            patch.setattr('sys.stderr', stream)
            event(LOG, 'stream.changed')
        assert json.loads(stream.getvalue())['event'] == 'stream.changed'
        stream.close()


def test_log_context_copy_and_failed_output_cannot_mutate_or_break_operation(monkeypatch):
    configure_logging()
    with bind_context(request_id='request-copy', details={'attempt':1}):
        snapshot = current_context()
        snapshot['details']['attempt'] = 99
        assert current_context()['details']['attempt'] == 1
        class BrokenOutput:
            def write(self, text):
                raise RuntimeError('broken stream')
            def flush(self):
                raise RuntimeError('broken stream')
        with monkeypatch.context() as patch:
            patch.setattr('sys.stderr', BrokenOutput())
            event(LOG, 'output.unavailable')


def test_legacy_logging_sanitizes_mapping_args_and_prefixed_environment_keys(capsys):
    configure_logging()
    LOG.warning('Headers %s', {'Cookie':'private-cookie-object','Authorization':'private-auth-object'})
    LOG.warning('OLLAMA_API_KEY=private-unknown-api-key SMTP_PASSWORD=private-smtp-password')
    LOG.warning('Error %s', RuntimeError('private-exception-body'))
    output = json.dumps(emitted(capsys))
    for secret in ('private-cookie-object','private-auth-object','private-unknown-api-key','private-smtp-password','private-exception-body'):
        assert secret not in output


def test_boot_identifier_changes_after_process_change(monkeypatch):
    import gianna.observability as module
    original = boot_id()
    process = module.os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(module.os, 'getpid', lambda: process+1)
        replacement = boot_id()
        assert replacement != original and boot_id() == replacement
    assert boot_id() != replacement


def test_provider_rejection_does_not_store_or_log_remote_response_content(cfg, caplog):
    from gianna.services.runtime import Ollama
    from gianna.services.settings import Settings
    confidential = 'private-provider-response-with-user-content'
    client = httpx.Client(base_url='https://provider.example.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text=confidential)))
    provider = Ollama(cfg, client)
    configure_logging(cfg)
    try:
        provider.chat([{'role':'user','content':'private-question'}], Settings(model='test-model'), timeout=10)
    except DomainError as exc:
        assert confidential not in str(exc.__cause__)
        assert safe_exception(exc)['causes'][0]['http_status'] == 401
    else:
        raise AssertionError('Expected a provider rejection')
    assert confidential not in caplog.text and 'private-question' not in caplog.text


def test_provider_retries_keep_http_reason_and_success_timing_without_content(cfg, monkeypatch, capsys):
    from gianna.services.runtime import Ollama
    from gianna.services.settings import Settings
    attempts = []
    def respond(request):
        attempts.append(True)
        if len(attempts) == 1:
            return httpx.Response(429, text='private-limit-response')
        return httpx.Response(200, json={'message':{'content':'private-generated-answer'}})
    client = httpx.Client(base_url='https://provider.example.test', transport=httpx.MockTransport(respond))
    monkeypatch.setattr('gianna.services.runtime.time.sleep', lambda delay: None)
    configure_logging(cfg)
    result = Ollama(cfg, client).chat([{'role':'user','content':'private-question'}], Settings(model='test-model'))
    assert result[0]['content'] == 'private-generated-answer'
    rows = emitted(capsys)
    retry = next(row for row in rows if row['event'] == 'provider.retry_scheduled')
    assert retry['fields']['exception']['http_status'] == 429
    assert retry['fields']['exception']['code'] == 'provider_http_retryable'
    completed = next(row for row in rows if row['event'] == 'provider.request_completed')
    assert completed['fields']['attempt'] == 2 and completed['fields']['duration_ms'] >= 0
    output = json.dumps(rows)
    for private in ('private-limit-response', 'private-generated-answer', 'private-question'):
        assert private not in output
