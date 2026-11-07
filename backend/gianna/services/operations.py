"""Sanitized technical events: stdout for operators and durable SQL correlation.

This is deliberately not a logging handler: an unavailable database must never
cause recursive logging or prevent the original operation from completing.
"""
import json
import logging
import time
import uuid

from ..observability import boot_id, current_context, event as emit, safe_exception, sanitize_fields

LOG = logging.getLogger(__name__)


def record_event(db, event, *, level='info', code=None, stage=None, job_id=None,
                 request_id=None, **details):
    event_id = uuid.uuid4().hex
    request_id=request_id or current_context().get('request_id')
    fields = sanitize_fields(details)
    encoded = json.dumps(fields, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(encoded) > 16000:
        fields = {'truncated': True, 'fields': sorted(fields)[:40]}
        encoded = json.dumps(fields, separators=(',', ':'))
    severity = {'debug': logging.DEBUG, 'warning': logging.WARNING,
                'error': logging.ERROR, 'critical': logging.CRITICAL}.get(level, logging.INFO)
    emit(LOG, event, level=severity, event_id=event_id, job_id=job_id,
         request_id=request_id, code=code, stage=stage, **fields)
    try:
        db.execute('INSERT INTO operational_events(id,at,boot_id,job_id,request_id,event,level,code,stage,details_json) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (event_id, time.time(), boot_id(), job_id, request_id,
                    event[:100], level[:16], code[:100] if code else None,
                    stage[:100] if stage else None, encoded))
    except Exception as exc:
        emit(LOG, 'operations.persistence_failed', level=logging.WARNING,
             event_id=event_id, job_id=job_id, exception=safe_exception(exc))
    return event_id
