"""Audit requirements and attest the narrow MariaDB Connector/C advisory case.

The pip-audit JSON is never filtered or rewritten. PYSEC-2026-217 remains a raw
finding; a separate decision can classify that finding as runtime_not_affected
only after measuring a patched Connector/C in the immutable deployment image.
All other findings, skipped dependencies and missing evidence fail closed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid


ADVISORY_IDS = frozenset({'PYSEC-2026-217', 'CVE-2026-44172', 'GHSA-pv9p-5w55-55jm'})
SOURCES = {
    'vendor_advisory': 'https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm',
    'python_metadata_issue': 'https://github.com/pypa/advisory-database/issues/400',
}
PROBE = (
    'import importlib.metadata,json,mariadb;'
    'print(json.dumps({"driver_name":"mariadb",'
    '"driver_version":importlib.metadata.version("mariadb"),'
    '"connector_c_version":list(mariadb.client_version_info)}))'
)


def connector_patched(version):
    """Only vendor-documented patched release lines qualify for this exception."""
    if not isinstance(version, (list, tuple)) or len(version) != 3:
        return False
    if any(type(part) is not int or part < 0 for part in version):
        return False
    major, minor, patch = version
    return major == 3 and ((minor == 3 and patch >= 19) or (minor == 4 and patch >= 9))


def classify(audit, runtime):
    """Pure policy decision. Test fixtures do not constitute runtime attestation."""
    errors = []
    dependencies = audit.get('dependencies') if isinstance(audit, dict) else None
    if not isinstance(dependencies, list) or not dependencies:
        return dict(passed=False, errors=['audit_dependencies_missing'], findings=[],
                    raw_findings=0, unresolved=0, runtime_not_affected=0, sources=SOURCES)
    if not isinstance(runtime, dict):
        runtime = {}
    if runtime.get('source') != 'docker_image' or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(runtime.get('image_id',''))):
        errors.append('runtime_image_not_attested')
    driver = [item for item in dependencies if isinstance(item, dict)
              and re.sub(r'[-_.]+', '-', str(item.get('name','')).lower()) == 'mariadb']
    if len(driver) != 1 or runtime.get('driver_name') != 'mariadb':
        errors.append('audited_runtime_driver_missing_or_ambiguous')
    elif not driver[0].get('version') or driver[0]['version'] != runtime.get('driver_version'):
        errors.append('audited_runtime_driver_version_mismatch')
    if not connector_patched(runtime.get('connector_c_version')):
        errors.append('connector_c_not_patched_or_unknown')
    evidence_valid = not errors
    findings = []
    for dependency_index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict) or not isinstance(dependency.get('vulns'), list):
            errors.append('audit_dependency_invalid')
            continue
        if dependency.get('skip_reason'):
            errors.append('audit_dependency_skipped')
        name = str(dependency.get('name',''))
        version = dependency.get('version')
        for vulnerability_index, vulnerability in enumerate(dependency['vulns']):
            record = dict(dependency=name, version=version, dependency_index=dependency_index,
                          vulnerability_index=vulnerability_index,
                          classification='unresolved', reason='outside_narrow_runtime_policy')
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get('id'),str):
                record.update(id=None, reason='audit_finding_invalid')
                findings.append(record)
                continue
            record['id'] = vulnerability['id']
            aliases = vulnerability.get('aliases',[])
            known = (re.sub(r'[-_.]+','-',name.lower()) == 'mariadb'
                     and vulnerability['id'] in ADVISORY_IDS
                     and isinstance(aliases,list)
                     and all(isinstance(alias,str) and alias in ADVISORY_IDS for alias in aliases))
            if known and evidence_valid:
                record.update(classification='runtime_not_affected',
                              reason='vendor_patched_connector_c_measured_in_same_driver_image',
                              image_id=runtime['image_id'], driver_version=runtime['driver_version'],
                              connector_c_version=list(runtime['connector_c_version']))
            elif known:
                record['reason'] = 'runtime_evidence_did_not_pass'
            findings.append(record)
    unresolved = sum(item['classification'] != 'runtime_not_affected' for item in findings)
    return dict(passed=not errors and unresolved == 0, errors=sorted(set(errors)),
                findings=findings, raw_findings=len(findings), unresolved=unresolved,
                runtime_not_affected=len(findings)-unresolved, sources=SOURCES)


def runtime_versions(image, run=subprocess.run):
    """Query an immutable image, isolated from the network, DB, env files and app."""
    if not image or image.startswith('-'):
        raise ValueError('invalid_runtime_image')
    inspected = run(['docker','image','inspect','--format','{{.Id}}',image],
                    capture_output=True,text=True,timeout=30)
    if inspected.returncode:
        raise RuntimeError('runtime_image_inspection_failed')
    image_id = inspected.stdout.strip()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id):
        raise ValueError('runtime_image_id_invalid')
    measured = run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                   '--security-opt','no-new-privileges:true','--entrypoint','python',image_id,
                   '-I','-c',PROBE],capture_output=True,text=True,timeout=60)
    if measured.returncode:
        raise RuntimeError('runtime_version_probe_failed')
    data = json.loads(measured.stdout)
    if not isinstance(data,dict) or set(data) != {'driver_name','driver_version','connector_c_version'}:
        raise ValueError('runtime_probe_schema_invalid')
    return dict(data,source='docker_image',requested_image=image,image_id=image_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-image',required=True)
    parser.add_argument('--output-dir',type=Path,default=Path('reports/security'))
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    destination = args.output_dir / (now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    destination.mkdir(parents=True,exist_ok=False)
    raw = destination/'pip-audit.json'
    report = dict(schema_version=1,generated_at=now.isoformat(),passed=False,sources=SOURCES)
    report['audit_environment'] = dict(python=list(sys.version_info[:3]),platform=sys.platform)
    try:
        report['pip_audit_version'] = importlib.metadata.version('pip-audit')
    except importlib.metadata.PackageNotFoundError:
        report['pip_audit_version'] = None
    stage = 'requirements_audit'
    audit = None
    before = None
    try:
        command = [sys.executable,'-m','pip_audit','-r','requirements.txt','-f','json','-o',str(raw)]
        result = subprocess.run(command,capture_output=True,text=True,timeout=900)
        report['pip_audit_exit_code'] = result.returncode
        if result.returncode not in {0,1} or not raw.is_file():
            raise RuntimeError('pip_audit_did_not_produce_a_complete_report')
        before = raw.read_bytes()
        audit = json.loads(before)
        stage = 'runtime_probe'
        runtime = runtime_versions(args.runtime_image)
        report['runtime'] = runtime
        stage = 'classification'
        report.update(classify(audit,runtime))
        # Preserve the auditor's finding and provenance byte for byte.
        if raw.read_bytes() != before:
            raise RuntimeError('raw_report_changed')
        report['raw_report'] = dict(path=raw.name,sha256=hashlib.sha256(before).hexdigest(),preserved=True)
        if (result.returncode == 1) != (report['raw_findings'] > 0):
            report.update(passed=False,errors=[*report['errors'],'audit_exit_code_inconsistent'])
    except Exception as exc:
        if isinstance(audit,dict) and 'findings' not in report:
            report.update(classify(audit,{}))
        report.update(passed=False,error_stage=stage,error_type=type(exc).__name__)
        # Exception text/stdout/stderr may contain resolver URLs. Keep only the
        # typed stage; the untouched public JSON is retained whenever available.
        if raw.is_file():
            content = raw.read_bytes()
            report['raw_report'] = dict(path=raw.name,sha256=hashlib.sha256(content).hexdigest(),
                                       preserved=before is None or content == before)
            if before is not None:
                report['raw_report']['original_sha256'] = hashlib.sha256(before).hexdigest()
    (destination/'decision.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary = {key:report.get(key) for key in ('passed','raw_findings','runtime_not_affected','unresolved','errors','error_stage','error_type') if key in report}
    print(json.dumps(dict(summary,report=str(destination/'decision.json')),ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
