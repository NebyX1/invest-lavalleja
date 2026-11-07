"""Pure gate classification tests; synthetic versions do not attest production."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts.audit_dependencies import classify, connector_patched, main, runtime_versions


IMAGE = 'sha256:'+'a'*64


def report(*extra):
    return {'dependencies':[
        {'name':'mariadb','version':'1.1.14','vulns':[{
            'id':'PYSEC-2026-217','aliases':['CVE-2026-44172','GHSA-pv9p-5w55-55jm'],
            'description':'Original finding remains visible.', 'fix_versions':[]}]},
        *extra], 'fixes':[]}


def evidence(version=(3,4,9),**changes):
    return dict(source='docker_image',requested_image='gianna:test',image_id=IMAGE,
                driver_name='mariadb',driver_version='1.1.14',connector_c_version=list(version),**changes)


@pytest.mark.parametrize('version',[(3,3,19),(3,3,20),(3,4,9),(3,4,10)])
def test_only_vendor_patched_client_lines_allow_measured_runtime_classification(version):
    original = report()
    snapshot = deepcopy(original)
    result = classify(original,evidence(version))
    assert result['passed'] and result['raw_findings'] == 1
    assert result['findings'][0]['classification'] == 'runtime_not_affected'
    assert original == snapshot and original['dependencies'][0]['vulns'][0]['id'] == 'PYSEC-2026-217'
    assert 'MariaDB/server/security' in result['sources']['vendor_advisory']


@pytest.mark.parametrize('version',[(3,4,7),(3,4,8),(3,3,18),(3,5,0),(4,0,0),(),(3,4),(3,4,True),None,'3.4.9'])
def test_unpatched_unknown_or_unrecognized_client_versions_fail_closed(version):
    assert not connector_patched(version)
    runtime = evidence()
    runtime['connector_c_version'] = version
    result = classify(report(),runtime)
    assert not result['passed'] and result['unresolved'] == 1


def test_driver_mismatch_and_non_docker_or_ambiguous_evidence_fail():
    for change in ({'driver_version':'1.1.15'},{'source':'host'},{'image_id':'mutable-tag'},
                   {'driver_name':'not-mariadb'}):
        runtime = evidence()
        runtime.update(change)
        assert not classify(report(),runtime)['passed']
    ambiguous = report({'name':'mariadb','version':'1.1.14','vulns':[]})
    assert not classify(ambiguous,evidence())['passed']


def test_another_advisory_is_never_ignored_even_on_patched_runtime():
    raw = report({'name':'other-library','version':'1.0','vulns':[{'id':'CVE-OTHER','aliases':[]}]})
    raw['dependencies'][0]['vulns'].append({'id':'PYSEC-OTHER','aliases':['CVE-OTHER']})
    result = classify(raw,evidence())
    assert not result['passed'] and result['raw_findings'] == 3
    assert result['runtime_not_affected'] == 1 and result['unresolved'] == 2
    assert {row['id'] for row in result['findings']} == {'PYSEC-2026-217','PYSEC-OTHER','CVE-OTHER'}


def test_known_id_on_another_package_or_conflicting_aliases_are_not_accepted():
    raw = report()
    raw['dependencies'][0]['name'] = 'unrelated-driver'
    assert not classify(raw,evidence())['passed']
    raw = report()
    raw['dependencies'][0]['vulns'][0]['aliases'].append('CVE-OTHER')
    assert not classify(raw,evidence())['passed']


@pytest.mark.parametrize('raw',[None,{},[],{'dependencies':[]},{'dependencies':[{}]}])
def test_missing_or_invalid_audit_is_not_a_success(raw):
    assert not classify(raw,evidence())['passed']


def test_skipped_dependency_blocks_success_and_keeps_known_finding():
    raw = report({'name':'unknown-package','version':'1','vulns':[],'skip_reason':'metadata unavailable'})
    result = classify(raw,evidence())
    assert not result['passed'] and 'audit_dependency_skipped' in result['errors']
    assert result['raw_findings'] == 1


def test_probe_uses_immutable_id_no_network_env_file_mount_or_bootstrap():
    commands = []
    def run(command,**options):
        commands.append(command)
        payload = IMAGE if len(commands)==1 else json.dumps({
            'driver_name':'mariadb','driver_version':'1.1.14','connector_c_version':[3,4,9]})
        return SimpleNamespace(returncode=0,stdout=payload)
    measured = runtime_versions('gianna:validation',run)
    assert measured['source'] == 'docker_image' and measured['image_id'] == IMAGE
    probe = commands[1]
    assert probe[probe.index('--network')+1] == 'none' and IMAGE in probe
    assert '-I' in probe and '--entrypoint' in probe
    for flag in ('--env','--env-file','--mount','--volume'):
        assert flag not in probe
    assert 'create_app' not in probe[-1] and 'dotenv' not in probe[-1] and 'connect(' not in probe[-1]


def test_main_preserves_exact_raw_report_and_has_no_ignore_flag(tmp_path,monkeypatch,capsys):
    import scripts.audit_dependencies as module
    raw = json.dumps(report(),indent=1).encode('utf8') + b'\n'
    commands = []
    def run(command,**options):
        commands.append(command)
        destination = module.Path(command[command.index('-o')+1])
        destination.write_bytes(raw)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module,'runtime_versions',lambda image:evidence())
    assert main(['--runtime-image','gianna:validation','--output-dir',str(tmp_path)]) == 0
    assert '--ignore-vuln' not in commands[0] and '--no-deps' not in commands[0]
    decision_path = module.Path(json.loads(capsys.readouterr().out)['report'])
    decision = json.loads(decision_path.read_text())
    assert decision['raw_findings'] == 1 and decision['runtime_not_affected'] == 1
    assert (decision_path.parent/'pip-audit.json').read_bytes() == raw
    assert decision['raw_report']['preserved']


def test_runtime_probe_failure_never_turns_the_raw_finding_into_success(tmp_path,monkeypatch,capsys):
    import scripts.audit_dependencies as module
    def run(command,**options):
        module.Path(command[command.index('-o')+1]).write_text(json.dumps(report()))
        return SimpleNamespace(returncode=1)
    def unavailable(image):
        raise RuntimeError('private-environment-or-resolver-output')
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module,'runtime_versions',unavailable)
    assert main(['--runtime-image','gianna:validation','--output-dir',str(tmp_path)]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary['error_stage'] == 'runtime_probe'
    decision = module.Path(summary['report']).read_text()
    assert 'private-environment-or-resolver-output' not in decision
    assert json.loads(decision)['raw_findings'] == 1 and json.loads(decision)['unresolved'] == 1
    assert (module.Path(summary['report']).parent/'pip-audit.json').exists()


def test_raw_report_change_is_detected_and_never_claimed_preserved(tmp_path,monkeypatch,capsys):
    import scripts.audit_dependencies as module
    destinations = []
    def run(command,**options):
        destination = module.Path(command[command.index('-o')+1])
        destination.write_text(json.dumps(report()))
        destinations.append(destination)
        return SimpleNamespace(returncode=1)
    def tampered(image):
        destinations[0].write_text('{"dependencies":[]}')
        return evidence()
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module,'runtime_versions',tampered)
    assert main(['--runtime-image','gianna:validation','--output-dir',str(tmp_path)]) == 1
    decision = json.loads(module.Path(json.loads(capsys.readouterr().out)['report']).read_text())
    assert not decision['raw_report']['preserved']
    assert decision['raw_report']['sha256'] != decision['raw_report']['original_sha256']


def test_inconsistent_auditor_exit_code_cannot_pass(tmp_path,monkeypatch,capsys):
    import scripts.audit_dependencies as module
    def run(command,**options):
        module.Path(command[command.index('-o')+1]).write_text(json.dumps(report()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module,'runtime_versions',lambda image:evidence())
    assert main(['--runtime-image','gianna:validation','--output-dir',str(tmp_path)]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert 'audit_exit_code_inconsistent' in summary['errors']
