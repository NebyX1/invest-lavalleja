"""Fixture-only attachment checks: source identity, preservation, and exclusive output."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from gianna.corpus import Corpus, Record, information_source_hash, load_corpus
from scripts import attach_information_views as attachment


def write_json(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


@pytest.fixture
def package(tmp_path):
    original = {
        'schema_version': 'gianna.corpus.v1',
        'document': {'id': 'fixture', 'title': 'Guía íntegra', 'filename': 'fixture.docx',
                     'cutoff_date': '2026-09-18', 'sha256': 'f' * 64,
                     'conversion_note': 'Transcripción sin verificación externa.'},
        'sources': [{'id': 'S01', 'title': 'Fuente íntegra', 'description': 'Conservar descripción.',
                     'url': 'https://example.test/fuente', 'locator': 'DOCX p0001'}],
        'records': [
            {'id': 'public-a', 'title': 'Registro público', 'audience': 'public',
             'text': 'Original.\n\nCon espacios y acentos: información.\tFin.',
             'conditions': ['Condición sustantiva.', 'Otra condición.'], 'source_refs': ['S01'],
             'evidence_type': 'hypothesis', 'cutoff_date': '2026-09-18', 'period': '2026',
             'zones': ['Z1'], 'source_locator': 'DOCX p0001', 'original_block_ids': ['p0001'],
             'original_sha256': 'a' * 64, 'opportunity_id': 'O01', 'enabled': True},
            {'id': 'internal-a', 'title': 'Registro interno', 'audience': 'internal',
             'text': 'Contenido interno intacto.', 'conditions': ['Condición interna.'],
             'source_refs': ['S01'], 'evidence_type': 'institutional_proposal', 'enabled': False},
            {'id': 'public-disabled', 'title': 'Público deshabilitado', 'audience': 'public',
             'text': 'Propuesta original.', 'enabled': False, 'evidence_type': 'institutional_proposal'},
            {'id': 'internal-default', 'title': 'Interno por defecto', 'text': 'Texto interno original.'},
            {'id': 'public-method', 'title': 'Método', 'audience': 'public',
             'text': 'El método original se conserva íntegro.', 'conditions': ['Límite metodológico.']},
        ],
        'conversion_report': {'original_note': 'Nota original del corpus.', 'counts': {'records': 5}},
    }
    # Even an existing native view on an internal record must remain exactly intact.
    internal = original['records'][1]
    internal['information_view'] = {
        'text': 'Vista interna preexistente.', 'kind': 'proposal',
        'source_sha256': information_source_hash(Record.model_validate(internal)),
    }
    source = tmp_path / 'fixture.gianna.json'
    reviewed = tmp_path / 'reviewed.json'
    output = tmp_path / 'attached.gianna.json'
    write_json(source, original)
    review = {
        'source_corpus_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'reviewer_note': 'PRIVATE_REVIEW_NOTE_TOP',
        # Deliberately different order: attachment must preserve the original record order.
        'records': [
            {'id': 'public-method', 'text': '', 'kind': 'methodology', 'note': 'PRIVATE_REVIEW_NOTE_METHOD'},
            {'id': 'public-disabled', 'text': 'Propuesta descriptiva revisada.', 'kind': 'proposal'},
            {'id': 'public-a', 'text': 'Descripción revisada.\nCon acentos.', 'kind': 'descriptive',
             'reviewer_note': 'PRIVATE_REVIEW_NOTE_ROW'},
        ],
    }
    write_json(reviewed, review)
    return {'source': source, 'reviewed': reviewed, 'output': output, 'original': original, 'review': review}


def run_attachment(package):
    return attachment.attach_information_views(package['source'], package['reviewed'], output=package['output'])


def assert_rejected(package, reason):
    before_source = package['source'].read_bytes()
    before_review = package['reviewed'].read_bytes()
    with pytest.raises(attachment.AttachmentError) as failed:
        run_attachment(package)
    assert failed.value.code == reason
    assert str(failed.value) == reason
    assert not package['output'].exists()
    assert package['source'].read_bytes() == before_source
    assert package['reviewed'].read_bytes() == before_review


def test_attaches_only_valid_views_preserves_all_original_content_and_roundtrips(package):
    before_source = package['source'].read_bytes()
    before_review = package['reviewed'].read_bytes()
    summary = run_attachment(package)
    result = json.loads(package['output'].read_bytes())
    stripped = deepcopy(result)
    original_stripped = deepcopy(package['original'])
    for before, after in zip(original_stripped['records'], stripped['records'], strict=True):
        before.pop('information_view', None)
        after.pop('information_view', None)
    assert stripped == original_stripped
    assert result['records'][1] == package['original']['records'][1]
    assert result['records'][3] == package['original']['records'][3]
    assert 'audience' not in result['records'][3]
    assert 'topic' not in result['records'][0]  # Do not expand omitted original defaults.
    assert result['conversion_report'] == package['original']['conversion_report']
    assert package['source'].read_bytes() == before_source
    assert package['reviewed'].read_bytes() == before_review
    assert b'PRIVATE_REVIEW_NOTE' not in package['output'].read_bytes()

    reviewed = {row['id']: row for row in package['review']['records']}
    for original, after in zip(package['original']['records'], result['records'], strict=True):
        if original.get('audience', 'internal') != 'public':
            continue
        assert after['information_view'] == {
            'text': reviewed[original['id']]['text'], 'kind': reviewed[original['id']]['kind'],
            'source_sha256': information_source_hash(Record.model_validate(original)),
        }
        assert after.get('enabled', True) == original.get('enabled', True)
        assert 'approved' not in after
    corpus = load_corpus(package['output'])
    assert Corpus.model_validate_json(corpus.model_dump_json()).model_dump() == corpus.model_dump()
    assert corpus.records[-1].information_view.text == ''
    assert summary == {
        'source_corpus_sha256': hashlib.sha256(before_source).hexdigest(),
        'reviewed_views_sha256': hashlib.sha256(before_review).hexdigest(),
        'output_sha256': hashlib.sha256(package['output'].read_bytes()).hexdigest(),
        'total_records': 5, 'public_records': 3, 'internal_records': 2, 'attached_views': 3,
    }


@pytest.mark.parametrize('change', ['wrong-hash', 'whitespace', 'bom', 'line-endings'])
def test_requires_hash_of_exact_source_bytes(package, change):
    if change == 'wrong-hash':
        package['review']['source_corpus_sha256'] = '0' * 64
        write_json(package['reviewed'], package['review'])
    else:
        raw = package['source'].read_bytes()
        raw = {'whitespace': raw + b' ', 'bom': b'\xef\xbb\xbf' + raw,
               'line-endings': raw.replace(b'\n', b'\r\n')}[change]
        package['source'].write_bytes(raw)
    assert_rejected(package, 'source_sha256_mismatch')


def test_bom_source_is_supported_when_exact_hash_matches(package):
    package['source'].write_bytes(b'\xef\xbb\xbf' + package['source'].read_bytes())
    package['review']['source_corpus_sha256'] = hashlib.sha256(package['source'].read_bytes()).hexdigest()
    write_json(package['reviewed'], package['review'])
    assert run_attachment(package)['attached_views'] == 3


@pytest.mark.parametrize('record_id', ['public-a', 'public-disabled', 'public-method'])
def test_requires_complete_public_coverage_including_disabled_records(package, record_id):
    package['review']['records'] = [row for row in package['review']['records'] if row['id'] != record_id]
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, 'incomplete_public_coverage')


def test_rejects_duplicate_review_ids(package):
    package['review']['records'].append(deepcopy(package['review']['records'][0]))
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, 'duplicate_record_id')


@pytest.mark.parametrize(('record_id', 'reason'), [
    ('unknown-private-id', 'unknown_record_id'),
    ('internal-a', 'internal_record_annotation'),
    ('internal-default', 'internal_record_annotation'),
])
def test_rejects_unknown_and_internal_annotations(package, record_id, reason):
    package['review']['records'].append({'id': record_id, 'text': 'PRIVATE_REVIEW_BODY', 'kind': 'proposal'})
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, reason)


@pytest.mark.parametrize('changes', [
    {'text': ''}, {'text': ' \t\n'}, {'text': 'á' * 8001}, {'text': None},
    {'kind': 'unknown'}, {'kind': 'Descriptive'},
])
def test_rejects_invalid_view_schema_before_writing(package, changes):
    package['review']['records'][-1].update(changes)
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, 'invalid_information_view')


@pytest.mark.parametrize('field', ['approved', 'source_sha256', 'information_view', 'unexpected'])
def test_review_rows_accept_only_explicit_view_fields_and_ignored_notes(package, field):
    package['review']['records'][0][field] = 'PRIVATE_EXTRA_FIELD'
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, 'invalid_review')


@pytest.mark.parametrize('target', ['existing-file', 'existing-directory', 'source', 'reviewed', 'source-alias'])
def test_never_overwrites_existing_outputs_or_inputs(package, target):
    if target == 'existing-file':
        package['output'].write_bytes(b'EXISTING_REFERENCE_MUST_SURVIVE')
        output = package['output']
    elif target == 'existing-directory':
        package['output'].mkdir()
        output = package['output']
    elif target == 'source-alias':
        output = package['source'].parent / 'unused' / '..' / package['source'].name
    else:
        output = package[target]
    before_source = package['source'].read_bytes()
    before_review = package['reviewed'].read_bytes()
    expected = 'output_exists' if target.startswith('existing') else 'input_output_collision'
    with pytest.raises(attachment.AttachmentError, match='^' + expected + '$'):
        attachment.attach_information_views(package['source'], package['reviewed'], output=output)
    assert package['source'].read_bytes() == before_source
    assert package['reviewed'].read_bytes() == before_review
    if target == 'existing-file':
        assert package['output'].read_bytes() == b'EXISTING_REFERENCE_MUST_SURVIVE'


def test_exclusive_creation_protects_output_that_appears_after_precheck(package, monkeypatch):
    check = attachment._check_output

    def raced_check(source, reviewed, output):
        check(source, reviewed, output)
        output.write_bytes(b'CONCURRENT_OUTPUT_MUST_SURVIVE')

    monkeypatch.setattr(attachment, '_check_output', raced_check)
    with pytest.raises(attachment.AttachmentError, match='^output_exists$'):
        run_attachment(package)
    assert package['output'].read_bytes() == b'CONCURRENT_OUTPUT_MUST_SURVIVE'


@pytest.mark.parametrize('invalid', ['bad-json', 'bad-schema', 'duplicate-json-key'])
def test_invalid_source_has_fixed_sanitized_reason(package, invalid):
    if invalid == 'bad-schema':
        package['original']['records'][0]['text'] = None
        write_json(package['source'], package['original'])
    elif invalid == 'duplicate-json-key':
        package['source'].write_bytes(b'{"records":[],"records":"PRIVATE_SOURCE_BODY"}')
    else:
        package['source'].write_bytes(b'PRIVATE_SOURCE_BODY invalid json')
    package['review']['source_corpus_sha256'] = hashlib.sha256(package['source'].read_bytes()).hexdigest()
    write_json(package['reviewed'], package['review'])
    assert_rejected(package, 'invalid_source_corpus' if invalid == 'bad-schema' else 'invalid_source_json')


@pytest.mark.parametrize('review', [None, [], {'records': []},
    {'source_corpus_sha256': 'A' * 64, 'records': []},
    {'source_corpus_sha256': 'a' * 64, 'records': {}, 'reviewer_note': 'PRIVATE_NOTE'},
])
def test_malformed_review_pack_is_rejected(package, review):
    write_json(package['reviewed'], review)
    assert_rejected(package, 'invalid_review')


def test_cli_success_prints_only_counts_and_hashes(package, capsys):
    assert attachment.main([str(package['source']), str(package['reviewed']), '--output', str(package['output'])]) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    summary = json.loads(captured.out)
    assert summary['attached_views'] == 3
    for key, value in summary.items():
        assert isinstance(value, int) or key.endswith('_sha256') and len(value) == 64
    assert str(package['source']) not in captured.out
    assert 'PRIVATE_REVIEW' not in captured.out


@pytest.mark.parametrize('failure', ['schema', 'coverage', 'missing-output', 'unknown-argument'])
def test_cli_failures_do_not_dump_document_notes_paths_or_validation_details(package, capsys, failure):
    args = [str(package['source']), str(package['reviewed'])]
    reason = 'invalid_arguments'
    if failure != 'missing-output':
        args += ['--output', str(package['output'])]
    if failure == 'schema':
        package['review']['records'][-1]['kind'] = 'PRIVATE_BAD_KIND'
        write_json(package['reviewed'], package['review'])
        reason = 'invalid_information_view'
    elif failure == 'coverage':
        package['review']['records'].pop()
        write_json(package['reviewed'], package['review'])
        reason = 'incomplete_public_coverage'
    elif failure == 'unknown-argument':
        args.append('--PRIVATE_ARGUMENT')
    assert attachment.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert json.loads(captured.err) == {'error': reason}
    assert not package['output'].exists()


@pytest.mark.parametrize('module', [False, True])
def test_cli_entrypoint_runs_without_application_setup(package, module):
    backend = Path(__file__).resolve().parents[1]
    command = [sys.executable]
    command += ['-m', 'scripts.attach_information_views'] if module else [str(backend / 'scripts/attach_information_views.py')]
    result = subprocess.run([*command, str(package['source']), str(package['reviewed']), '--output', str(package['output'])],
                            cwd=backend, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0
    assert result.stderr == ''
    assert json.loads(result.stdout)['attached_views'] == 3
