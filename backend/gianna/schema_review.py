"""Review physical SQL layout; repair only known, additive MariaDB invariants.

History alone is insufficient after an interrupted restore. Defaults and columns
are inspected independently. Unknown missing editorial data is never fabricated.
"""
from pathlib import Path
import json

CORE_COLUMNS={table:set(columns) for table,columns in json.loads(
    (Path(__file__).parent/'schema_contract.json').read_text(encoding='utf-8')).items()}
DEFAULTS = {
    ('bases','description'): '', ('bases','document_json'): '{}', ('bases','report_json'): '{}',
    ('versions','profile_json'): '{}', ('versions','report_json'): '{}',
    ('audit','details_json'): '{}', ('queries','source_ids_json'): '[]',
    ('queries','retrieval_trace_json'): '{}', ('queries','cited_source_ids_json'): '[]',
}
for _table,_column in DEFAULTS:
    CORE_COLUMNS.setdefault(_table,set()).add(_column)
_QUEUE_ADDITIONS = {'stage','error_code','error_stage','action','retryable','heartbeat_at',
                    'last_attempt_at','boot_id','recovery_boot_id'}


def _columns(connection, maria):
    if maria:
        rows=connection.execute('SELECT TABLE_NAME AS t,COLUMN_NAME AS c,COLUMN_DEFAULT AS d '
                                'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()').fetchall()
        result={}
        for row in rows:result.setdefault(row['t'],{})[row['c']]=row['d']
        return result
    result={}
    for table in set(CORE_COLUMNS)|{table for table,_ in DEFAULTS}:
        result[table]={row['name']:row['dflt_value'] for row in connection.execute('PRAGMA table_info('+table+')').fetchall()}
    return result


def _drift(columns, maria):
    missing={table:sorted(required-set(columns.get(table,{})))
             for table,required in CORE_COLUMNS.items() if not required<=set(columns.get(table,{}))}
    defaults=[]
    if maria:
        for (table,column),expected in DEFAULTS.items():
            actual=columns.get(table,{}).get(column)
            if actual is None or str(actual) not in {expected,"'"+expected.replace("'","''")+"'"}:
                defaults.append({'table':table,'column':column,'expected':expected})
    return missing,defaults


def review_schema(connection, maria, *, apply=False):
    columns=_columns(connection,maria)
    missing,defaults=_drift(columns,maria)
    repairs=[]
    # Only rerun DDL designed to be idempotent. Never replay authentication or
    # editorial migrations, reset history, or synthesize rows from table names.
    irreparable=any(table not in {'job_events','operational_events','jobs'} or
                    (table in {'job_events','operational_events'} and bool(columns.get(table))) or
                    (table=='jobs' and set(fields)-(_QUEUE_ADDITIONS|{'attempts','available_at'}))
                    for table,fields in missing.items())
    if apply and maria and not irreparable:
        if defaults:repairs.append(3)
        if set(missing.get('jobs',[])) & {'attempts','available_at'}:repairs.append(4)
        if set(missing.get('jobs',[])) & _QUEUE_ADDITIONS or 'job_events' in missing or 'operational_events' in missing:
            repairs.append(5)
        directory=Path(__file__).parent/'migrations_mariadb'
        for revision in repairs:
            source=(directory/f'{revision:03}.sql').read_text(encoding='utf-8')
            for statement in source.split(';'):
                if statement.strip():connection.execute(statement)
        if repairs:
            connection.commit()
            missing,defaults=_drift(_columns(connection,maria),maria)
    return {'ok':not missing and not defaults,'missing_columns':missing,
            'default_drift':defaults,'repairs':repairs,
            'requires_restore':bool(irreparable),
            'code':None if not missing and not defaults else 'database_schema_incompatible',
            'action':'Restaurá un esquema compatible desde respaldo; no se inventarán columnas editoriales ni datos perdidos.' if missing else
                     'Volvé a desplegar para restaurar los valores por defecto conocidos del esquema.' if defaults else ''}
