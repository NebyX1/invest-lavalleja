"""Compile reviewed descriptive knowledge without overwriting its originals.

Inputs are an original native corpus, its hash-bound reviewed views, and an
explicit source-backed supplement. Original public records become an internal
documentary archive; existing internal records stay unchanged. The output is a
new native corpus, never an approval, index, publication or factual certificate.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from gianna.corpus import Corpus, DocumentInfo, DocumentaryContent, InformationView, Record, Source, information_source_hash, load_corpus


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_corpus(original_path, reviewed_path, supplement_path):
    raw = Path(original_path).read_bytes()
    original = load_corpus(Path(original_path))
    reviewed = load_corpus(Path(reviewed_path))
    views = {r.id: r.information_view for r in reviewed.records if r.audience == 'public'}
    supplement = json.loads(Path(supplement_path).read_text(encoding='utf-8'))
    edition = supplement['edition_date']
    records, mapping = [], []
    for source in original.records:
        if source.audience != 'public':
            records.append(source.model_copy(deep=True))
            continue
        view = views.get(source.id)
        if view is None or view.source_sha256 != information_source_hash(source):
            raise ValueError('Reviewed view missing or stale: ' + source.id)
        archive = source.model_copy(deep=True)
        archive.id = 'original.' + source.id
        archive.audience = 'internal'
        archive.information_view = None
        records.append(archive)
        row = {'original_id': source.id, 'archive_id': archive.id, 'kind': view.kind,
               'original_record_sha256': information_source_hash(source)}
        if not view.text.strip():
            row['public_record_id'] = None
            mapping.append(row)
            continue
        # Procedures keep their exact documentary detail. Other blocks index the
        # reviewed descriptive statements, not an author's business checklist.
        record = source.model_copy(deep=True)
        if view.kind != 'procedure':
            record.text = view.text
            record.conditions = []  # Material scope is inside the reviewed text.
            record.documentary = DocumentaryContent(text=source.text,conditions=list(source.conditions))
        record.information_view = InformationView(text=view.text, kind=view.kind,
                                                  source_sha256=information_source_hash(record))
        records.append(record)
        row['public_record_id'] = record.id
        row['compiled_record_sha256'] = information_source_hash(record)
        mapping.append(row)
    source_ids = {s.id for s in original.sources}
    new_sources = [Source.model_validate({**s, 'accessed_at': edition}) for s in supplement['sources']]
    if any(s.id in source_ids for s in new_sources):
        raise ValueError('Supplement source IDs must be new')
    for raw_record in supplement['records']:
        item = deepcopy(raw_record)
        kind = item.pop('kind')
        item.update(audience='public', enabled=True, cutoff_date=edition,
                    section=item.get('section', 'Complemento documental ' + edition))
        record = Record.model_validate(item)
        record.information_view = InformationView(text=record.text, kind=kind,
                                                  source_sha256=information_source_hash(record))
        records.append(record)
    amendments = []
    for amendment in supplement.get('amendments', []):
        matches = [r for r in records if r.id == amendment['id'] and r.audience == 'public']
        if len(matches) != 1 or information_source_hash(matches[0]) != amendment['expected_sha256']:
            raise ValueError('Amendment target missing or stale')
        record = matches[0]
        changes = amendment['changes']
        if not set(changes) <= {'text', 'documentary', 'source_refs', 'cutoff_date', 'period'}:
            raise ValueError('Amendments cannot change identity, audience or review state')
        updated = Record.model_validate(record.model_dump() | changes | {'information_view': None})
        if not set(record.source_refs) <= set(updated.source_refs):
            raise ValueError('Amendments must preserve original references')
        updated.information_view = InformationView(text=updated.text, kind=record.information_view.kind,
                                                  source_sha256=information_source_hash(updated))
        records[records.index(record)] = updated
        for row in mapping:
            if row.get('public_record_id') == updated.id:
                row['compiled_record_sha256'] = information_source_hash(updated)
        amendments.append({'id':updated.id, 'before':information_source_hash(record),
                           'after':information_source_hash(updated)})
    provenance = {
        'compiler': 'invest-descriptive-v1', 'original_corpus_sha256': digest(raw),
        'reviewed_corpus_sha256': digest(Path(reviewed_path).read_bytes()),
        'supplement_sha256': digest(Path(supplement_path).read_bytes()),
        'original_conversion_report': deepcopy(original.conversion_report),
        'mapping': mapping, 'source_preservation': 'Original public records archived as internal; existing internal records unchanged.',
        'amendments': amendments,
        'publication': 'Unapproved draft; no automatic indexing or activation.',
        'review_scope': 'Source-backed editorial restructuring, not independent legal or commercial certification.',
    }
    identity = digest(json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode())
    result = Corpus(document=DocumentInfo(id='invest-informativa-' + edition,
        title='Invest Lavalleja · conocimiento descriptivo ampliado · ' + edition,
        filename='Invest_Lavalleja_informativa_' + edition + '.gianna.json', sha256=identity,
        cutoff_date=edition, conversion_note=supplement['scope_note']),
        sources=[s.model_copy(deep=True) for s in original.sources] + new_sources,
        records=records, conversion_report=provenance)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('reviewed', type=Path)
    parser.add_argument('--supplement', type=Path, default=Path(__file__).resolve().parents[1] / 'samples/invest_supplement_20261108.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.original, args.reviewed, args.supplement)]
    if args.output.resolve() in paths or args.output.exists():
        parser.error('Output must be new and distinct from every input')
    corpus = compile_corpus(args.original, args.reviewed, args.supplement)
    raw = (json.dumps(corpus.model_dump(mode='json'), ensure_ascii=False, indent=2) + '\n').encode()
    # Validate serialized, nested views and links before writing the delivery.
    Corpus.model_validate_json(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as output:
        output.write(raw)
    print(json.dumps({'path': str(args.output), 'sha256': digest(raw), 'records': len(corpus.records),
                      'public': sum(r.audience == 'public' for r in corpus.records),
                      'internal': sum(r.audience == 'internal' for r in corpus.records),
                      'sources': len(corpus.sources), 'published': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
