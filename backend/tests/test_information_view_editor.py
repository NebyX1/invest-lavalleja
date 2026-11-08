"""Real Flask editor requests, with isolated test SQL and no paid generation."""
import json
import time

import pytest

from gianna import create_app
from gianna.corpus import Record, information_source_hash
from gianna.security import token_hash
from gianna.services.settings import Settings


@pytest.fixture
def editor(cfg, corpus):
    app = create_app(cfg)
    app.config['TESTING'] = True
    services = app.extensions['gianna']
    source = corpus.records[0]
    data = source.model_dump()
    data['information_view'] = {'text': 'Una propuesta documentada. <script>texto</script>',
                                'kind': 'proposal', 'source_sha256': information_source_hash(source)}
    corpus.records[0] = Record.model_validate(data)
    base = services.knowledge.import_corpus(corpus, 'Base editorial de prueba', 'actor')
    services.knowledge.approve_public(base, 'actor')
    _, version = services.knowledge.enqueue_build(base, Settings(), 'actor')
    row = services.db.one("SELECT * FROM records WHERE base_id=? AND audience='public'", (base,))
    client = app.test_client()
    user = services.security.create_user('views@example.test', 'Editor', 'a-long-test-password', 'owner', 'email')
    raw = 'isolated-view-editor-session'
    now = time.time()
    services.db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',
                        (token_hash(raw), user, now, now, now + 1000, now))
    with client.session_transaction() as session:
        session['sid'] = raw
        session['csrf'] = 'view-editor-csrf'
    path = f'/admin/bases/{base}/records/{row["id"]}'
    form = {key: data.get(key) or '' for key in ('id', 'title', 'topic', 'audience', 'evidence_type',
                                               'section', 'text', 'period', 'source_locator', 'cutoff_date')}
    form.update(csrf='view-editor-csrf', enabled='yes', conditions='\n---\n'.join(data['conditions']),
                source_refs=','.join(data['source_refs']), zones=','.join(data['zones']),
                information_view_present='yes', information_view_enabled='yes',
                information_view_text=data['information_view']['text'], information_view_kind='proposal')
    return client, services, base, version, row['id'], path, form


def test_editor_displays_both_source_and_view_safely(editor):
    client, _, _, _, _, path, _ = editor
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Contenido del registro' in html and 'Vista informativa para Gianna' in html
    assert 'Condiciones y alcance del registro' in html
    assert '<script>texto</script>' not in html and '&lt;script&gt;texto&lt;/script&gt;' in html
    assert 'unsafe-inline' not in response.headers['Content-Security-Policy']


def test_source_edit_invalidates_unchanged_view_without_mutating_snapshot(editor):
    client, services, _, version, row, path, form = editor
    snapshot = services.db.one('SELECT content_json FROM version_records WHERE version_id=?', (version,))['content_json']
    response = client.post(path, data={**form, 'text': 'Contenido original actualizado.'},
                           headers={'Origin': 'http://localhost'})
    assert response.status_code == 302
    saved = services.db.one('SELECT approved,content_json FROM records WHERE id=?', (row,))
    data = json.loads(saved['content_json'])
    assert data['text'] == 'Contenido original actualizado.' and saved['approved'] == 0
    assert 'information_view' not in data
    assert services.db.one('SELECT content_json FROM version_records WHERE version_id=?', (version,))['content_json'] == snapshot
    assert services.knowledge.active() is None
    page = client.get(response.location).get_data(as_text=True)
    assert 'vista informativa anterior quedó invalidada' in page


def test_explicit_updated_view_binds_to_new_source_and_requires_review(editor):
    client, services, _, _, row, path, form = editor
    response = client.post(path, data={**form, 'text': 'Una fuente revisada.',
                           'information_view_text': 'Una propuesta según la fuente revisada.'},
                           headers={'Origin': 'http://localhost'})
    assert response.status_code == 302
    saved = services.db.one('SELECT approved,content_json FROM records WHERE id=?', (row,))
    record = Record.model_validate_json(saved['content_json'])
    assert record.information_view is not None
    assert record.information_view.source_sha256 == information_source_hash(record)
    assert record.information_view.text == 'Una propuesta según la fuente revisada.'
    assert saved['approved'] == 0 and services.knowledge.active() is None


def test_editor_can_remove_view_without_removing_original(editor):
    client, services, _, _, row, path, form = editor
    form.pop('information_view_enabled')
    response = client.post(path, data=form, headers={'Origin': 'http://localhost'})
    assert response.status_code == 302
    data = json.loads(services.db.one('SELECT content_json FROM records WHERE id=?', (row,))['content_json'])
    assert data['text'] == form['text'] and 'information_view' not in data
