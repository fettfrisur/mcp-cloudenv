"""Single-host durable feedback loop. No model is trusted to schedule successors."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from .worker import atomic_json

STAGES = ('plan', 'plan_review', 'build', 'review', 'verify', 'branch_review')
ROLES = dict(zip(STAGES, ('builder', 'reviewer', 'builder', 'reviewer', 'verifier', 'reviewer')))
HERE = Path(__file__).resolve().parent
MAX_REPORT = 128 * 1024
MAX_EVIDENCE = 16 * 1024 * 1024


def command(argv, cwd=None, timeout=30):
    return subprocess.run(argv, cwd=cwd, timeout=timeout, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def git(repo, *args, timeout=30):
    return command(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgSign=false',
                    '-c', 'user.name=Agent Loop', '-c', 'user.email=agent-loop@localhost',
                    '-C', str(repo), *args], timeout=timeout)


@contextmanager
def controller_lock(root):
    with (Path(root) / 'controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('another controller owns this run') from error
        yield


def finite_positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate_config(config):
    required = {'backend', 'timeout', 'check_timeout', 'max_attempts',
                'max_remediations', 'max_total_attempts', 'check'}
    if not isinstance(config, dict) or not required.issubset(config):
        raise ValueError('configuration is missing required fields')
    for key in ('timeout', 'check_timeout'):
        if not finite_positive(config[key]):
            raise ValueError(f'{key} must be finite and positive')
    for key in ('max_attempts', 'max_remediations', 'max_total_attempts'):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    if config['backend'] not in ('command', 'codex'):
        raise ValueError('unknown backend')
    vectors = [config['check']]
    if config['backend'] == 'command':
        if not isinstance(config.get('commands'), dict) or set(config['commands']) != set(ROLES.values()):
            raise ValueError('commands must define builder, reviewer and verifier')
        vectors += list(config['commands'].values())
    for vector in vectors:
        if not isinstance(vector, list) or not vector or any(not isinstance(a, str) or not a for a in vector):
            raise ValueError('commands must be nonempty argv arrays')
    for key in ('executable', 'model'):
        if key in config and (not isinstance(config[key], str) or not config[key].strip()):
            raise ValueError(f'{key} must be a nonempty string')


def preflight(config):
    validate_config(config)
    problems = []
    if not sys.platform.startswith('linux') or not hasattr(os, 'pidfd_open'):
        problems.append('Linux with pidfd support is required by the worker supervisor')
    executables = ['git', config['check'][0]]
    if config['backend'] == 'command':
        executables += [v[0] for v in config['commands'].values()]
    else:
        executables.append(config.get('executable', 'codex'))
    for executable in sorted(set(executables)):
        if not shutil.which(executable):
            problems.append(f'executable unavailable: {executable}')
    if config['backend'] == 'codex' and not problems:
        try:
            command([config.get('executable', 'codex'), 'login', 'status'], timeout=10)
        except (OSError, subprocess.SubprocessError):
            problems.append('Codex authentication preflight failed; run codex login on the host')
    return problems


def schema():
    evidence = {'type': 'object', 'additionalProperties': False,
                'properties': {'path': {'type': 'string'}, 'detail': {'type': 'string'}},
                'required': ['path', 'detail']}
    finding = {'type': 'object', 'additionalProperties': False,
               'properties': {'id': {'type': 'string'}, 'detail': {'type': 'string'}},
               'required': ['id', 'detail']}
    properties = {k: {'type': 'string'} for k in
                  ('run_id', 'attempt_id', 'stage', 'role', 'input_revision', 'summary')}
    properties.update(version={'type': 'integer', 'enum': [1]},
                      verdict={'type': 'string', 'enum': ['ready', 'pass', 'changes_requested', 'blocked']},
                      findings={'type': 'array', 'items': finding},
                      evidence={'type': 'array', 'items': evidence})
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties)}


def validate_report(report, request):
    if not isinstance(report, dict) or set(report) != set(schema()['properties']):
        raise ValueError('report fields differ from the required contract')
    if type(report['version']) is not int or report['version'] != 1:
        raise ValueError('unsupported report version')
    for key in ('run_id', 'attempt_id', 'stage', 'role', 'input_revision'):
        if report[key] != request[key]:
            raise ValueError(f'report {key} does not match active request')
    if not isinstance(report['summary'], str) or len(report['summary'].strip()) < 20:
        raise ValueError('report summary must contain at least 20 characters')
    verdict = report['verdict']
    allowed = {'ready', 'blocked'} if request['role'] == 'builder' else {'pass', 'changes_requested', 'blocked'}
    if verdict not in allowed:
        raise ValueError('verdict is invalid for this role')
    if not isinstance(report['findings'], list) or not isinstance(report['evidence'], list):
        raise ValueError('findings and evidence must be arrays')
    if len(report['evidence']) > 32:
        raise ValueError('at most 32 evidence files are allowed')
    ids = set()
    for finding in report['findings']:
        if (not isinstance(finding, dict) or set(finding) != {'id', 'detail'} or
            not isinstance(finding['id'], str) or not finding['id'].strip() or
            finding['id'] in ids or not isinstance(finding['detail'], str) or len(finding['detail'].strip()) < 10):
            raise ValueError('invalid or duplicate finding')
        ids.add(finding['id'])
    if (verdict == 'changes_requested') != bool(report['findings']):
        raise ValueError('only changes_requested may contain findings, and must contain them')
    if verdict != 'blocked' and not report['evidence']:
        raise ValueError('a usable result requires file evidence')
    workspace = Path(request['workspace']).resolve()
    for item in report['evidence']:
        if (not isinstance(item, dict) or set(item) != {'path', 'detail'} or
            not isinstance(item['path'], str) or not isinstance(item['detail'], str) or len(item['detail'].strip()) < 10):
            raise ValueError('invalid evidence')
        path = (workspace / item['path']).resolve()
        if not path.is_relative_to(workspace) or not path.is_file() or '.git' in path.relative_to(workspace).parts:
            raise ValueError('evidence must reference an existing workspace file outside .git')


def hash_evidence(report, workspace):
    artifacts, total = [], 0
    for item in report['evidence']:
        path = Path(workspace) / item['path']
        if path.stat().st_size > MAX_EVIDENCE:
            raise ValueError('evidence file exceeds 16 MiB')
        digest, size = hashlib.sha256(), 0
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                size += len(chunk)
                total += len(chunk)
                if size > MAX_EVIDENCE or total > MAX_EVIDENCE * 2:
                    raise ValueError('evidence exceeds byte budget')
                digest.update(chunk)
        artifacts.append({**item, 'sha256': digest.hexdigest(), 'bytes': size})
    return artifacts


class Controller:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / 'state.sqlite3').is_file():
            raise ValueError('run not initialized')
        self.db = sqlite3.connect(self.root / 'state.sqlite3', timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.children = {}
        if not self.db.execute('SELECT data FROM state WHERE id=1').fetchone():
            self.db.close()
            raise ValueError('run initialization incomplete; use a new empty run directory')

    def close(self):
        for process in self.children.values():
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self.db.close()

    @classmethod
    def create(cls, root, project, goal, config):
        root, project = Path(root).resolve(), Path(project).resolve()
        validate_config(config)
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError('goal must be nonempty')
        if root.is_relative_to(project):
            raise ValueError('run state must be outside the source repository')
        if root.exists() and any(root.iterdir()):
            raise ValueError('run directory must be empty')
        if git(project, 'status', '--porcelain'):
            raise ValueError('source must be clean; commit intended inputs first')
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        with controller_lock(root):
            command(['git', 'clone', '--no-hardlinks', '--', str(project), str(root / 'repository')], timeout=60)
            baseline = git(root / 'repository', 'rev-parse', 'HEAD')
            state = dict(version=1, run_id=uuid.uuid4().hex, status='ready', stage='plan',
                         revision=baseline, baseline=baseline, goal=goal, config=config,
                         current_attempt=None, stage_attempts=0, total_attempts=0,
                         remediations=0, feedback=[], diagnostic='', retry_after=0)
            db = sqlite3.connect(root / 'initializing.sqlite3')
            db.execute('PRAGMA synchronous=FULL')
            with db:
                db.executescript('CREATE TABLE state (id INTEGER PRIMARY KEY, data TEXT NOT NULL);'
                                 'CREATE TABLE attempts (id TEXT PRIMARY KEY, data TEXT NOT NULL);'
                                 'CREATE TABLE events (seq INTEGER PRIMARY KEY, time REAL, data TEXT NOT NULL);')
                db.execute('INSERT INTO state VALUES (1, ?)', (json.dumps(state),))
            db.close()
            os.replace(root / 'initializing.sqlite3', root / 'state.sqlite3')
            descriptor = os.open(root, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return cls(root)

    def state(self):
        return json.loads(self.db.execute('SELECT data FROM state WHERE id=1').fetchone()[0])

    def attempt(self, identity):
        row = self.db.execute('SELECT data FROM attempts WHERE id=?', (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, state, event, attempt=None):
        with self.db:
            self.db.execute('UPDATE state SET data=? WHERE id=1', (json.dumps(state),))
            if attempt:
                self.db.execute('INSERT OR REPLACE INTO attempts VALUES (?, ?)',
                                (attempt['attempt_id'], json.dumps(attempt)))
            self.db.execute('INSERT INTO events(time, data) VALUES (?, ?)',
                            (time.time(), json.dumps({'event': event, 'stage': state['stage'],
                                                      'attempt': state['current_attempt'],
                                                      'diagnostic': state['diagnostic']})))

    def block(self, reason, attempt=None):
        state = self.state()
        state.update(status='blocked', diagnostic=reason)
        if attempt:
            attempt['status'] = 'blocked'
        self.save(state, 'blocked', attempt)

    def claim(self):
        state = self.state()
        config = state['config']
        if state['status'] != 'ready':
            return None
        if state['total_attempts'] >= config['max_total_attempts']:
            self.block('total attempt budget exhausted')
            return None
        identity = uuid.uuid4().hex
        directory = self.root / 'attempts' / identity
        attempt = dict(attempt_id=identity, run_id=state['run_id'], stage=state['stage'],
                       role=ROLES[state['stage']], input_revision=state['revision'],
                       number=state['stage_attempts'] + 1,
                       deadline=time.time() + config['timeout'], status='active',
                       workspace=str(directory / 'workspace'), directory=str(directory))
        state.update(status='running', current_attempt=identity,
                     stage_attempts=state['stage_attempts'] + 1,
                     total_attempts=state['total_attempts'] + 1)
        self.save(state, 'claimed', attempt)
        return attempt

    def launch(self, attempt):
        state = self.state()
        directory = Path(attempt['directory'])
        directory.mkdir(parents=True)
        remaining = lambda: max(0.01, min(60, attempt['deadline'] - time.time()))
        command(['git', 'clone', '--no-hardlinks', '--', str(self.root / 'repository'),
                 attempt['workspace']], timeout=remaining())
        git(attempt['workspace'], 'checkout', '--detach', attempt['input_revision'], timeout=remaining())
        role_prompt = (HERE / 'prompts' / f"{attempt['role']}.md").read_text()
        request = dict(attempt, baseline=state['baseline'], goal=state['goal'],
                       feedback=state['feedback'], previous_error=state['diagnostic'],
                       acceptance_command=state['config']['check'], **{
                           k: v for k, v in state['config'].items()
                           if k in ('backend', 'executable', 'model')})
        request['command'] = state['config'].get('commands', {}).get(attempt['role'], [])
        request['executable'] = state['config'].get('executable', 'codex')
        request['prompt'] = (role_prompt + '\nReturn only a JSON report matching the schema.\n'
                             'Request identities, goal, baseline, feedback and acceptance command:\n' +
                             json.dumps({k: v for k, v in request.items() if k != 'prompt'}, indent=2))
        atomic_json(directory / 'request.json', request)
        atomic_json(directory / 'schema.json', schema())
        with (directory / 'supervisor.log').open('ab') as log:
            self.children[attempt['attempt_id']] = subprocess.Popen([sys.executable, str(HERE / 'worker.py'), str(directory)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)

    def fail(self, attempt, reason):
        state = self.state()
        if state['current_attempt'] != attempt['attempt_id'] or state['status'] != 'running':
            return False
        attempt.update(status='failed', error=reason)
        state.update(status='ready', current_attempt=None, diagnostic=reason,
                     retry_after=time.time() + min(5, 0.25 * 2 ** min(state['stage_attempts'], 4)))
        if state['stage_attempts'] >= state['config']['max_attempts']:
            state.update(status='blocked', diagnostic=f'stage retry budget exhausted: {reason}')
        self.save(state, 'attempt_failed', attempt)
        return True

    def promote(self, attempt):
        workspace = attempt['workspace']
        marker = Path(attempt['directory']) / 'snapshot.json'
        if attempt['role'] == 'builder' and marker.is_file():
            revision = json.loads(marker.read_text())['revision']
            git(self.root / 'repository', 'fetch', '--no-tags', workspace,
                f"{revision}:refs/loop/candidates/{attempt['attempt_id']}")
            return revision
        if git(workspace, 'rev-parse', 'HEAD') != attempt['input_revision']:
            raise ValueError('actor changed Git HEAD; leave changes uncommitted')
        if attempt['role'] == 'builder':
            git(workspace, 'add', '-A')
            if git(workspace, 'status', '--porcelain'):
                git(workspace, 'commit', '-m', f"Agent loop {attempt['stage']} {attempt['attempt_id']}")
            revision = git(workspace, 'rev-parse', 'HEAD')
            atomic_json(marker, {'revision': revision})
            # Import before DB acceptance. A crash can leave an orphan object,
            # never a falsely accepted revision. Reimport is safe.
            git(self.root / 'repository', 'fetch', '--no-tags', workspace,
                f"{revision}:refs/loop/candidates/{attempt['attempt_id']}")
            return revision
        if git(workspace, 'status', '--porcelain'):
            raise ValueError('non-builder modified source')
        return attempt['input_revision']

    def accept(self, attempt_id, report, revision):
        state = self.state()
        attempt = self.attempt(attempt_id)
        if (not attempt or state['status'] != 'running' or state['current_attempt'] != attempt_id or
            attempt['status'] != 'active' or state['revision'] != attempt['input_revision']):
            return False
        # Freeze a validated copy before committing the transition. An orphan
        # report on a crash is harmless; SQLite remains authoritative.
        atomic_json(Path(attempt['directory']) / 'accepted.json', report)
        attempt.update(status='accepted', result=report, output_revision=revision)
        state.update(revision=revision, current_attempt=None, stage_attempts=0,
                     diagnostic='', retry_after=0)
        verdict = report['verdict']
        state['feedback'].append({'stage': attempt['stage'], 'revision': revision, 'report': report})
        if verdict == 'blocked':
            state.update(status='blocked', diagnostic=report['summary'])
        elif verdict == 'changes_requested':
            state['remediations'] += 1
            state.update(status='ready', stage='plan' if attempt['stage'] == 'plan_review' else 'build')
            if state['remediations'] > state['config']['max_remediations']:
                state.update(status='blocked', diagnostic='remediation budget exhausted')
        elif attempt['stage'] == 'branch_review':
            state.update(status='complete')
        else:
            state.update(status='ready', stage=STAGES[STAGES.index(attempt['stage']) + 1])
        self.save(state, 'accepted', attempt)
        return True

    def acceptance_check(self, attempt):
        """Execute the fixed command on a separate clone of exactly the input."""
        state = self.state()
        checkdir = Path(attempt['directory']) / 'acceptance'
        logdir = Path(attempt['directory'])
        result = {'argv': state['config']['check'], 'revision': attempt['input_revision']}
        invocation = logdir / 'check-invocation'
        invocation.mkdir(exist_ok=True)
        request_path = invocation / 'request.json'
        if not request_path.exists():
            # No worker can exist before this durable dispatch intent. A partial
            # setup from a crashed controller may safely be recreated.
            if checkdir.exists():
                shutil.rmtree(checkdir)
            command(['git', 'clone', '--no-hardlinks', '--', str(self.root / 'repository'), str(checkdir)], timeout=60)
            git(checkdir, 'checkout', '--detach', attempt['input_revision'])
            atomic_json(request_path, dict(backend='command', workspace=str(checkdir),
                        command=state['config']['check'], prompt='',
                        deadline=time.time() + state['config']['check_timeout']))
            with (invocation / 'supervisor.log').open('ab') as log:
                self.children[attempt['attempt_id'] + '/check'] = subprocess.Popen(
                    [sys.executable, str(HERE / 'worker.py'), str(invocation)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = json.loads(request_path.read_text())['deadline']
        while not (invocation / 'exit.json').is_file():
            if time.time() > deadline + 5:
                raise ValueError('acceptance deadline expired without completion record')
            time.sleep(.05)
        child = self.children.pop(attempt['attempt_id'] + '/check', None)
        if child:
            child.wait(timeout=2)
        completion = json.loads((invocation / 'exit.json').read_text())
        if completion['timed_out'] or completion['error'] or completion['exit_code'] is None:
            raise ValueError(f'acceptance invocation failed: {completion}')
        result['exit_code'] = completion['exit_code']
        # Tests may generate ignored artifacts, but changing source invalidates
        # evidence even when their exit code is zero.
        if git(checkdir, 'rev-parse', 'HEAD') != attempt['input_revision'] or git(checkdir, 'status', '--porcelain'):
            raise ValueError('acceptance command modified source')
        atomic_json(logdir / 'check.json', result)
        return result

    def reconcile(self):
        state = self.state()
        if state['status'] != 'running':
            return
        attempt = self.attempt(state['current_attempt'])
        directory = Path(attempt['directory'])
        exit_path = directory / 'exit.json'
        if not exit_path.is_file():
            if time.time() > attempt['deadline'] + 5:
                self.fail(attempt, 'invocation deadline expired without a completion record')
            return
        child = self.children.pop(attempt['attempt_id'], None)
        if child:
            child.wait(timeout=2)
        try:
            completion = json.loads(exit_path.read_text())
            if completion['exit_code'] != 0 or completion['timed_out'] or completion['error']:
                raise ValueError(f'invocation failed: {completion}')
            request = json.loads((directory / 'request.json').read_text())
            report_path = directory / 'report.json'
            if not report_path.is_file() or report_path.stat().st_size > MAX_REPORT:
                raise ValueError('report missing or exceeds 128 KiB')
            report = json.loads(report_path.read_text())
            validate_report(report, request)
            atomic_json(directory / 'evidence.json', hash_evidence(report, attempt['workspace']))
            revision = self.promote(attempt)
            if attempt['stage'] == 'verify' and report['verdict'] == 'pass':
                check = self.acceptance_check(attempt)
                if check['exit_code'] != 0:
                    report = dict(report, verdict='changes_requested',
                                  summary='The controller acceptance command failed on the candidate revision.',
                                  findings=[{'id': 'acceptance-command',
                                             'detail': f"Command {check['argv']} exited {check['exit_code']}; inspect {directory / 'check-invocation'} logs"}])
            self.accept(attempt['attempt_id'], report, revision)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            self.fail(attempt, f'{type(error).__name__}: {error}')

    def run(self, poll=0.1):
        with controller_lock(self.root):
            state = self.state()
            if state['status'] in ('blocked', 'complete'):
                return state
            problems = preflight(state['config'])
            if problems:
                self.block('; '.join(problems))
            while self.state()['status'] not in ('blocked', 'complete'):
                self.reconcile()
                state = self.state()
                if state['status'] == 'ready' and time.time() >= state['retry_after']:
                    attempt = self.claim()
                    if attempt:
                        try:
                            self.launch(attempt)
                        except (OSError, ValueError, subprocess.SubprocessError) as error:
                            self.fail(attempt, f'setup/dispatch failed: {error}')
                time.sleep(poll)
            return self.state()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('init')
    create.add_argument('--state', required=True)
    create.add_argument('--project', required=True)
    create.add_argument('--goal-file', required=True)
    create.add_argument('--config', required=True)
    for name in ('run', 'status', 'events'):
        p = sub.add_parser(name)
        p.add_argument('--state', required=True)
    probe = sub.add_parser('preflight')
    probe.add_argument('--config', required=True)
    args = parser.parse_args(argv)
    controller = None
    try:
        if args.action == 'preflight':
            problems = preflight(json.loads(Path(args.config).read_text()))
            print(json.dumps({'ready': not problems, 'problems': problems}, indent=2))
            return 2 if problems else 0
        if args.action == 'init':
            controller = Controller.create(args.state, args.project, Path(args.goal_file).read_text(),
                                           json.loads(Path(args.config).read_text()))
        else:
            controller = Controller(args.state)
        if args.action == 'events':
            for seq, timestamp, data in controller.db.execute('SELECT seq, time, data FROM events ORDER BY seq'):
                print(json.dumps({'seq': seq, 'time': timestamp, **json.loads(data)}))
            return 0
        state = controller.run() if args.action == 'run' else controller.state()
        print(json.dumps(state, indent=2))
        return 2 if state['status'] == 'blocked' else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1
    finally:
        if controller:
            controller.close()


if __name__ == '__main__':
    raise SystemExit(main())
