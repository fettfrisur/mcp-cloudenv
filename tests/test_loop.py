"""Exercise product feedback, real subprocess faults, and durable crash windows."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from loop.controller import Controller, MAX_EVIDENCE, controller_lock, git, hash_evidence, preflight, validate_config

ROOT = Path(__file__).resolve().parents[1]
ACTOR = ROOT / 'tests' / 'fixtures' / 'loop_actor.py'


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        git(self.project, 'init')
        (self.project / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.project / '.gitignore').write_text('__pycache__/\n')
        git(self.project, 'add', '.')
        git(self.project, 'commit', '-m', 'Seed a real addition defect')
        self.config = dict(backend='command', commands={role: [sys.executable, str(ACTOR), '{request}']
                                                      for role in ('builder', 'reviewer', 'verifier')},
                           timeout=3, check_timeout=3, max_attempts=2,
                           max_remediations=4, max_total_attempts=30,
                           check=[sys.executable, '-c', 'from calc import add; assert add(2, 3) == 5; assert add(-3, 1) == -2'])

    def controller(self, scenario='', **changes):
        config = copy.deepcopy(self.config)
        config.update(changes)
        if scenario:
            for argv in config['commands'].values():
                argv.append(scenario)
        controller = Controller.create(self.root / 'run', self.project, 'Repair addition with independent evidence', config)
        self.addCleanup(controller.close)
        return controller

    def run_loop(self, scenario='', **changes):
        controller = self.controller(scenario, **changes)
        return controller, controller.run(poll=.01)

    def attempts(self, controller):
        return [json.loads(row[0]) for row in controller.db.execute('SELECT data FROM attempts ORDER BY rowid')]

    def test_feedback_repairs_real_file_and_preserves_source(self):
        c, state = self.run_loop()
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(state['remediations'], 1)
        self.assertIn('a + b', git(c.root / 'repository', 'show', state['revision'] + ':calc.py'))
        self.assertIn('a - b', (self.project / 'calc.py').read_text())
        verification = next(a for a in self.attempts(c) if a['stage'] == 'verify')
        check = json.loads((Path(verification['directory']) / 'check.json').read_text())
        self.assertEqual(check['exit_code'], 0)
        self.assertEqual(check['revision'], state['revision'])

    def test_plan_and_branch_feedback_paths(self):
        for scenario in ('plan-reject', 'branch-reject'):
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as root:
                    config = copy.deepcopy(self.config)
                    for argv in config['commands'].values():
                        argv.append(scenario)
                    c = Controller.create(Path(root) / 'run', self.project, 'Repair addition with evidence', config)
                    try:
                        state = c.run(poll=.01)
                        self.assertEqual(state['status'], 'complete')
                        self.assertEqual(state['remediations'], 2)
                    finally:
                        c.close()

    def test_fixed_check_overrules_false_agent_pass(self):
        c, state = self.run_loop('check-catches')
        self.assertEqual(state['status'], 'complete')
        self.assertTrue(any(f['report']['findings'] and f['report']['findings'][0]['id'] == 'acceptance-command'
                            for f in state['feedback']))

    def test_each_role_recovers_from_faults(self):
        for stage in ('plan', 'review', 'verify'):
            for fault in ('empty', 'garbage', 'crash', 'hang', 'wrong'):
                with self.subTest(stage=stage, fault=fault), tempfile.TemporaryDirectory() as root:
                    config = copy.deepcopy(self.config)
                    if fault == 'hang':
                        config['timeout'] = .5
                    for argv in config['commands'].values():
                        argv.append(f'{stage}:{fault}')
                    c = Controller.create(Path(root) / 'run', self.project, 'Repair addition with evidence', config)
                    try:
                        self.assertEqual(c.run(poll=.01)['status'], 'complete')
                        self.assertTrue(any(a['status'] == 'failed' for a in self.attempts(c)))
                    finally:
                        c.close()

    def test_bad_evidence_source_edits_and_large_reports_rejected(self):
        for fault in ('escape', 'missing', 'edit', 'large'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as root:
                config = copy.deepcopy(self.config)
                for argv in config['commands'].values():
                    argv.append(f'review:{fault}:always')
                c = Controller.create(Path(root) / 'run', self.project, 'Repair addition with evidence', config)
                try:
                    state = c.run(poll=.01)
                    self.assertEqual(state['status'], 'blocked')
                    self.assertIn('retry budget exhausted', state['diagnostic'])
                    self.assertEqual(c.run()['total_attempts'], state['total_attempts'])
                finally:
                    c.close()

    def test_explicit_block_and_budgets_are_durable(self):
        c, state = self.run_loop('review:blocked')
        self.assertEqual(state['status'], 'blocked')
        self.assertIn('external service', state['diagnostic'])
        self.assertEqual(c.run()['total_attempts'], state['total_attempts'])

    def test_total_and_remediation_caps(self):
        for changes, reason in (({'max_total_attempts': 2}, 'total attempt'),
                                ({'max_remediations': 1}, 'remediation')):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as root:
                config = copy.deepcopy(self.config)
                config.update(changes)
                for argv in config['commands'].values():
                    argv.append('branch-reject')
                c = Controller.create(Path(root) / 'run', self.project, 'Repair addition with evidence', config)
                try:
                    state = c.run(poll=.01)
                    self.assertEqual(state['status'], 'blocked')
                    self.assertIn(reason, state['diagnostic'])
                finally:
                    c.close()

    def test_persisted_claim_without_dispatch_expires_then_recovers(self):
        c = self.controller()
        old = c.claim()
        old['deadline'] = time.time() - 10
        c.save(c.state(), 'test_crash_before_launch', old)
        state = c.run(poll=.01)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(c.attempt(old['attempt_id'])['status'], 'failed')

    def test_completion_survives_controller_process_death(self):
        c = self.controller()
        c.close()
        code = ('import os; from loop.controller import Controller; '
                f'c=Controller({str(c.root)!r}); a=c.claim(); c.launch(a); os._exit(17)')
        p = subprocess.run([sys.executable, '-c', code], cwd=ROOT)
        self.assertEqual(p.returncode, 17)
        resumed = Controller(c.root)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.run(poll=.01)['status'], 'complete')

    def test_crash_after_import_before_accept_is_recoverable(self):
        c = self.controller()
        a = c.claim()
        c.launch(a)
        deadline = time.time() + 5
        while not (Path(a['directory']) / 'exit.json').exists() and time.time() < deadline:
            time.sleep(.01)
        with patch.object(c, 'accept', side_effect=RuntimeError('crash after object import')):
            with self.assertRaises(RuntimeError):
                c.reconcile()
        self.assertEqual(c.state()['status'], 'running')
        self.assertEqual(c.run(poll=.01)['status'], 'complete')

    def test_crash_after_verification_does_not_rerun_or_block(self):
        c = self.controller(max_attempts=1)
        original = c.accept
        def crash_at_verify(*args):
            if c.state()['stage'] == 'verify':
                raise RuntimeError('controller died after check before acceptance')
            return original(*args)
        with patch.object(c, 'accept', side_effect=crash_at_verify):
            with self.assertRaises(RuntimeError):
                c.run(poll=.01)
        attempt_id = c.state()['current_attempt']
        record = Path(c.attempt(attempt_id)['directory']) / 'check-invocation' / 'exit.json'
        before = record.stat().st_mtime_ns
        self.assertEqual(c.run(poll=.01)['status'], 'complete')
        self.assertEqual(record.stat().st_mtime_ns, before)

    def test_controller_dies_while_verification_is_running(self):
        config = copy.deepcopy(self.config)
        config['check'] = [sys.executable, '-c', 'import time; time.sleep(1); from calc import add; assert add(2,3)==5']
        c = Controller.create(self.root / 'run', self.project, 'Repair addition with evidence', config)
        self.addCleanup(c.close)
        process = subprocess.Popen([sys.executable, '-m', 'loop.controller', 'run', '--state', str(c.root)],
                                   cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 10
            while time.time() < deadline:
                records = list((c.root / 'attempts').glob('*/check-invocation/request.json'))
                if records:
                    break
                time.sleep(.01)
            self.assertTrue(records)
            process.kill()
            process.wait(timeout=3)
            self.assertEqual(c.run(poll=.01)['status'], 'complete')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_acceptance_timeout_and_source_edits_do_not_pass(self):
        for script in ('import time; time.sleep(60)',
                       "from pathlib import Path; Path('calc.py').write_text('broken')"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as root:
                config = copy.deepcopy(self.config)
                config.update(check=[sys.executable, '-c', script], check_timeout=.2, max_attempts=1)
                c = Controller.create(Path(root) / 'run', self.project, 'Repair addition with evidence', config)
                try:
                    self.assertEqual(c.run(poll=.01)['status'], 'blocked')
                    self.assertEqual(c.state()['stage'], 'verify')
                finally:
                    c.close()

    def test_duplicate_and_late_delivery_cannot_advance(self):
        c, state = self.run_loop()
        accepted = next(a for a in self.attempts(c) if a['status'] == 'accepted')
        self.assertFalse(c.accept(accepted['attempt_id'], accepted['result'], accepted['output_revision']))
        self.assertFalse(c.accept('unknown', {}, state['revision']))
        self.assertEqual(c.state(), state)
        # Even a late abandoned workspace edit has no effect on the candidate.
        Path(accepted['workspace'], 'calc.py').write_text('late corruption')
        self.assertIn('a + b', git(c.root / 'repository', 'show', state['revision'] + ':calc.py'))

    def test_background_descendant_stopped_before_snapshot(self):
        c, state = self.run_loop('build:background')
        self.assertEqual(state['status'], 'complete')
        time.sleep(.3)
        self.assertIn('a + b', git(c.root / 'repository', 'show', state['revision'] + ':calc.py'))
        for attempt in self.attempts(c):
            if attempt['stage'] == 'build':
                self.assertNotIn('late damage', Path(attempt['workspace'], 'calc.py').read_text())

    def test_setup_failure_retries_boundedly(self):
        c = self.controller()
        with patch.object(c, 'launch', side_effect=subprocess.TimeoutExpired('clone', .1)):
            state = c.run(poll=.01)
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['total_attempts'], 2)

    def test_controller_lock_and_missing_executable(self):
        c = self.controller()
        with controller_lock(c.root):
            with self.assertRaisesRegex(RuntimeError, 'another controller'):
                c.run()
        config = copy.deepcopy(self.config)
        config['commands']['builder'][0] = 'no-such-loop-executable'
        self.assertTrue(preflight(config))
        for invalid in (0, -1, float('inf'), float('nan')):
            config['timeout'] = invalid
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_codex_adapter_argv_stdin_schema_and_output_contract(self):
        shim = self.root / 'codex-test-shim'
        shim.write_text(f'#!{sys.executable}\n' + (ROOT / 'tests' / 'fixtures' / 'codex_shim.py').read_text()
                        .replace("Path(__file__).with_name('loop_actor.py')", repr(str(ACTOR))))
        shim.chmod(0o700)
        config = copy.deepcopy(self.config)
        config.update(backend='codex', executable=str(shim), model='fixture-model')
        c = Controller.create(self.root / 'run', self.project, 'Repair addition with evidence', config)
        self.addCleanup(c.close)
        self.assertEqual(c.run(poll=.01)['status'], 'complete')
        self.assertTrue(list((c.root / 'attempts').glob('*/events.jsonl')))

    def test_evidence_hashing_has_a_byte_budget(self):
        evidence = self.project / 'large-evidence.log'
        with evidence.open('wb') as stream:
            stream.truncate(MAX_EVIDENCE + 1)
        with self.assertRaisesRegex(ValueError, '16 MiB'):
            hash_evidence({'evidence': [{'path': evidence.name, 'detail': 'Oversized test evidence file.'}]}, self.project)

    def test_cli_exits_nonzero_for_blocked_run(self):
        c = self.controller('review:garbage:always', max_attempts=1)
        result = subprocess.run([sys.executable, '-m', 'loop.controller', 'run', '--state', str(c.root)],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'blocked')

    def test_crash_after_accept_before_dispatch_preserves_ready_stage(self):
        c = self.controller()
        identity = c.claim()
        c.launch(identity)
        until = time.time() + 5
        while not (Path(identity['directory']) / 'exit.json').exists() and time.time() < until:
            time.sleep(.01)
        c.reconcile()
        self.assertEqual(c.state()['stage'], 'plan_review')
        self.assertEqual(c.state()['status'], 'ready')
        resumed = Controller(c.root)
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.run(poll=.01)['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
