#!/usr/bin/env python3
"""Attach manually reviewed views to a new native corpus, without approval or publication.

Hashes establish source identity, not factual truth or the meaning of a reviewed view.
Optional ``note`` and ``reviewer_note`` keys in the review pack or its rows are ignored;
they are never copied into the corpus. This script does not load application configuration.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from gianna.corpus import Corpus, InformationView, information_source_hash


IGNORED_REVIEW_FIELDS = frozenset({'note', 'reviewer_note'})


class AttachmentError(ValueError):
    """A fixed reason code safe to print without document content or filesystem paths."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('nonfinite_json_value')


def _parse_json(raw, reason):
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise AttachmentError(reason) from None


def _read_bytes(path):
    try:
        return path.read_bytes()
    except (OSError, ValueError):
        raise AttachmentError('input_read_failed') from None


def _check_output(source, reviewed, output):
    try:
        if output.resolve() in (source.resolve(), reviewed.resolve()):
            raise AttachmentError('input_output_collision')
        if output.exists() or output.is_symlink():
            raise AttachmentError('output_exists')
    except AttachmentError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise AttachmentError('invalid_output_path') from None


def _review_rows(review, source_sha256):
    required = {'source_corpus_sha256', 'records'}
    if (not isinstance(review, dict) or not required <= review.keys()
            or review.keys() - required - IGNORED_REVIEW_FIELDS
            or not isinstance(review['records'], list)
            or not isinstance(review['source_corpus_sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', review['source_corpus_sha256'])):
        raise AttachmentError('invalid_review')
    if review['source_corpus_sha256'] != source_sha256:
        raise AttachmentError('source_sha256_mismatch')
    return review['records']


def _validated_views(corpus, rows):
    records = {record.id: record for record in corpus.records}
    public_ids = {record.id for record in corpus.records if record.audience == 'public'}
    views = {}
    required = {'id', 'text', 'kind'}
    for row in rows:
        if (not isinstance(row, dict) or not required <= row.keys()
                or row.keys() - required - IGNORED_REVIEW_FIELDS
                or not isinstance(row['id'], str)):
            raise AttachmentError('invalid_review')
        record_id = row['id']
        if record_id in views:
            raise AttachmentError('duplicate_record_id')
        if record_id not in records:
            raise AttachmentError('unknown_record_id')
        record = records[record_id]
        if record.audience != 'public':
            raise AttachmentError('internal_record_annotation')
        try:
            views[record_id] = InformationView(text=row['text'], kind=row['kind'],
                                              source_sha256=information_source_hash(record)).model_dump(mode='json')
        except (ValidationError, ValueError, TypeError):
            raise AttachmentError('invalid_information_view') from None
    if views.keys() != public_ids:
        raise AttachmentError('incomplete_public_coverage')
    return views


def _without_views(data):
    result = deepcopy(data)
    for record in result['records']:
        record.pop('information_view', None)
    return result


def _verify_and_serialize(original, attached, source_corpus, views):
    if _without_views(attached) != _without_views(original):
        raise AttachmentError('original_preservation_failed')
    for before, after, record in zip(original['records'], attached['records'], source_corpus.records, strict=True):
        if record.audience == 'internal' and before != after:
            raise AttachmentError('original_preservation_failed')
    try:
        validated = Corpus.model_validate(attached)
        serialized = (json.dumps(attached, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        restored = Corpus.model_validate_json(serialized)
        if restored.model_dump(mode='json') != validated.model_dump(mode='json'):
            raise AttachmentError('native_roundtrip_failed')
        # A syntactically valid but stale view would have been silently invalidated by Record.
        for record in restored.records:
            if record.audience == 'public':
                if record.information_view is None or record.information_view.model_dump(mode='json') != views[record.id]:
                    raise AttachmentError('native_roundtrip_failed')
        if Corpus.model_validate_json(restored.model_dump_json()).model_dump() != restored.model_dump():
            raise AttachmentError('native_roundtrip_failed')
    except (ValidationError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, AttachmentError):
            raise
        raise AttachmentError('native_roundtrip_failed') from None
    return serialized


def attach_information_views(source_path, reviewed_path, *, output):
    """Validate both input files, create only a new output file, and return counts/hashes.

    Complete public coverage includes disabled public records. Internal records and
    all original metadata remain untouched, including omitted optional fields.
    """
    source_path, reviewed_path, output = Path(source_path), Path(reviewed_path), Path(output)
    _check_output(source_path, reviewed_path, output)
    source_bytes, review_bytes = _read_bytes(source_path), _read_bytes(reviewed_path)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    rows = _review_rows(_parse_json(review_bytes, 'invalid_review_json'), source_sha256)
    original = _parse_json(source_bytes, 'invalid_source_json')
    try:
        corpus = Corpus.model_validate(original)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise AttachmentError('invalid_source_corpus') from None
    views = _validated_views(corpus, rows)
    attached = deepcopy(original)
    for record, normalized in zip(attached['records'], corpus.records, strict=True):
        if normalized.audience == 'public':
            record['information_view'] = views[normalized.id]
    serialized = _verify_and_serialize(original, attached, corpus, views)
    try:
        # Exclusive creation also protects against an output appearing after the precheck.
        with output.open('xb') as writer:
            writer.write(serialized)
    except FileExistsError:
        raise AttachmentError('output_exists') from None
    except (OSError, ValueError):
        raise AttachmentError('output_write_failed') from None
    return {
        'source_corpus_sha256': source_sha256,
        'reviewed_views_sha256': hashlib.sha256(review_bytes).hexdigest(),
        'output_sha256': hashlib.sha256(serialized).hexdigest(),
        'total_records': len(corpus.records),
        'public_records': len(views),
        'internal_records': len(corpus.records) - len(views),
        'attached_views': len(views),
    }


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise AttachmentError('invalid_arguments')


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('reviewed_views', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        summary = attach_information_views(args.source, args.reviewed_views, output=args.output)
    except AttachmentError as exc:
        print(json.dumps({'error': exc.code}), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
