#!/usr/bin/env python3
"""Track ground-truth claims and verification evidence for any Git project."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from cloudenv import EnvError, capture, digest, write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot(project):
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                   '--exclude-standard'], cwd=project)
    paths = sorted(set(raw.decode().split('\0')) - {''})
    hashes = {}
    for name in paths:
        path = project / name
        if path.is_symlink():
            hashes[name] = hashlib.sha256(str(path.readlink()).encode()).hexdigest()
        elif path.is_file():
            hashes[name] = digest(path)
        else:
            hashes[name] = None
    return hashes


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def begin(project, goal, ledger):
    project = project.resolve()
    ledger = ledger.resolve()
    if ledger.is_relative_to(project):
        raise EnvError('Store the audit ledger outside the project to avoid self-invalidation')
    if ledger.exists():
        raise EnvError('Ledger exists; continue it rather than overwriting prior work')
    write_json(ledger, {
        'schema': 1, 'project': str(project), 'goal': goal, 'started_at': now(),
        'baseline_commit': capture(['git', 'rev-parse', 'HEAD'], cwd=project),
        'baseline_files': snapshot(project), 'evidence': {}, 'claims': [],
        'scope_notes': [],
    })
    print(f'Audit started: {ledger}')


def load(ledger):
    data = json.loads(ledger.read_text())
    if data['schema'] != 1:
        raise EnvError('Unknown ledger schema')
    return data, Path(data['project'])


def observe(ledger, evidence_id, command):
    data, project = load(ledger)
    if evidence_id in data['evidence']:
        raise EnvError('Evidence ID already exists; use a new ID for a retry')
    before = fingerprint(snapshot(project))
    start = now()
    code = subprocess.run(command, cwd=project).returncode
    after = fingerprint(snapshot(project))
    data['evidence'][evidence_id] = {
        'kind': 'command', 'command': command, 'started_at': start, 'checked_at': now(),
        'exit_code': code, 'source_fingerprint': before, 'source_unchanged': before == after,
        'interpretation': 'Exit status only. Describe the actual assertion in the claim.',
    }
    write_json(ledger, data)
    return code


def inspect_file(ledger, evidence_id, path):
    data, project = load(ledger)
    if evidence_id in data['evidence']:
        raise EnvError('Evidence ID already exists')
    target = (project / path).resolve()
    if not target.is_relative_to(project) or not target.is_file():
        raise EnvError('File evidence must resolve inside the project')
    data['evidence'][evidence_id] = {
        'kind': 'file', 'path': str(target.relative_to(project)),
        'sha256': digest(target), 'checked_at': now(),
        'interpretation': 'Static source evidence, not proof of runtime behavior',
    }
    write_json(ledger, data)


def validate(data, project, current=None):
    current = snapshot(project) if current is None else current
    current_hash = fingerprint(current)
    baseline = data['baseline_files']
    changed = {p for p in set(baseline) | set(current) if baseline.get(p) != current.get(p)}
    errors, unresolved, covered = [], [], set()
    claims = data.get('claims', [])
    evidence = data.get('evidence', {})
    if not claims:
        errors.append('No claims: state what was checked, including for read-only audits')
    seen = set()
    for claim in claims:
        claim_id = claim.get('id', '<missing>')
        if claim_id in seen or claim_id == '<missing>':
            errors.append(f'Duplicate/missing claim ID: {claim_id}')
        seen.add(claim_id)
        covered.update(claim.get('files', []))
        if not claim.get('statement') or not claim.get('reasoning'):
            errors.append(f'{claim_id}: statement and evidence interpretation are required')
        disposition = claim.get('status')
        if disposition not in ('verified', 'blocked', 'out-of-scope'):
            errors.append(f'{claim_id}: status must be verified, blocked, or out-of-scope')
        if disposition == 'blocked':
            unresolved.append(claim_id)
        # Every relevant boundary must be followed or explicitly scoped out.
        boundaries = claim.get('chain', [])
        if not boundaries:
            errors.append(f'{claim_id}: no chain of relevant boundaries')
        kinds = set()
        for link in boundaries:
            if not link.get('layer') or not link.get('finding'):
                errors.append(f'{claim_id}: each boundary needs layer and finding')
            refs = link.get('evidence', [])
            if disposition == 'verified' and not refs:
                errors.append(f'{claim_id}: verified boundary lacks evidence')
            for ref in refs:
                item = evidence.get(ref)
                if item is None:
                    errors.append(f'{claim_id}: unknown evidence {ref}')
                    continue
                kind = item.get('kind')
                kinds.add(kind)
                if kind == 'command':
                    if not item.get('source_unchanged') or item.get('source_fingerprint') != current_hash:
                        errors.append(f'{claim_id}: command evidence {ref} is stale')
                    if item.get('exit_code') != 0 and disposition == 'verified' and not link.get('expected_failure'):
                        errors.append(f'{claim_id}: failed command {ref} needs explicit expected_failure interpretation')
                elif kind == 'file':
                    path = (project / item['path']).resolve()
                    if not path.is_relative_to(project) or not path.is_file() or digest(path) != item['sha256']:
                        errors.append(f'{claim_id}: file evidence {ref} is stale')
                elif kind == 'external':
                    if not all(item.get(k) for k in ['source', 'checked_at', 'observation', 'subject']):
                        errors.append(f'{claim_id}: external evidence {ref} lacks source/time/subject/observation')
                else:
                    errors.append(f'{claim_id}: unsupported evidence kind for {ref}')
        if disposition == 'verified' and claim.get('behavioral', False) and not kinds.intersection({'command', 'external'}):
            errors.append(f'{claim_id}: behavioral claims cannot rely on source files alone')
    for path in sorted(changed - covered):
        errors.append(f'Changed file has no claim/disposition: {path}')
    return {'schema': 1, 'checked_at': now(), 'changed_files': sorted(changed),
            'errors': errors, 'blocked_claims': unresolved,
            'status': 'invalid' if errors else ('blocked' if unresolved else 'complete'),
            'limits': 'Checks ledger integrity, freshness, and coverage; agent judgment must assess evidence quality.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['begin', 'observe', 'file', 'check'])
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--goal')
    parser.add_argument('--id')
    parser.add_argument('--path')
    parser.add_argument('--output', type=Path)
    arguments = sys.argv[1:]
    extra = []
    if '--' in arguments:
        index = arguments.index('--')
        arguments, extra = arguments[:index], arguments[index + 1:]
    args = parser.parse_args(arguments)
    if args.command == 'begin':
        if not args.project or not args.goal:
            parser.error('begin requires --project and --goal')
        begin(args.project, args.goal, args.ledger)
    elif args.command == 'observe':
        if not args.id or not extra:
            parser.error('observe requires --id and a command after --')
        return observe(args.ledger, args.id, extra)
    elif args.command == 'file':
        if not args.id or not args.path:
            parser.error('file requires --id and --path')
        inspect_file(args.ledger, args.id, args.path)
    else:
        data, project = load(args.ledger)
        result = validate(data, project)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return {'complete': 0, 'blocked': 2, 'invalid': 1}[result['status']]
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (EnvError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'chain: {error}', file=sys.stderr)
        sys.exit(1)
