import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cloudenv as env
import chain


class RuntimeTests(unittest.TestCase):
    def test_policy_rejects_prerelease_and_wrong_major(self):
        with self.assertRaises(env.EnvError):
            env.version('24.22.1-rc.1')
        self.assertEqual(env.version('v24.22.1'), (24, 22, 1))
        bad = copy.deepcopy(env.policy())
        bad['node']['major'] = 26
        with patch.object(env, 'read_json', return_value=bad):
            with self.assertRaises(env.EnvError):
                env.policy()

    def test_update_check_stays_in_selected_major(self):
        cfg = env.policy()
        releases = [{'version': 'v26.99.0'}, {'version': 'v24.23.0'},
                    {'version': 'v24.22.1'}, {'version': 'v24.24.0-rc.1'}]
        self.assertEqual(env.choose_candidate(releases, cfg)['version'], 'v24.23.0')
        with self.assertRaises(env.EnvError):
            env.choose_candidate([{'version': 'v26.12.1'}], cfg)

    def test_installer_rejects_checksum_before_extracting(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(env, 'STATE', Path(temp)), patch.object(env, 'fetch', return_value=b'bad archive'):
                with self.assertRaisesRegex(env.EnvError, 'checksum'):
                    env.bootstrap()
                self.assertFalse((Path(temp) / 'toolchains').exists())

    def test_existing_binary_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)
            (dest / 'bin').mkdir()
            (dest / 'bin/node').write_text('not the installed binary')
            env.write_json(dest / '.receipt.json', {
                'archive_sha256': env.policy()['node']['sha256'][env.machine_key()],
                'node_sha256': '0' * 64})
            with patch.object(env, 'toolchain_dir', return_value=dest):
                with self.assertRaisesRegex(env.EnvError, 'binary changed'):
                    env.managed_env()

    def test_lockfile_change_and_missing_dependencies_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / 'app'
            project.mkdir()
            (project / 'package.json').write_text('{"name":"atproto-mcp"}')
            (project / 'package-lock.json').write_text('{}')
            (project / 'node_modules').mkdir()
            (project / 'node_modules/.package-lock.json').write_text('{}')
            cfg = env.profile('atproto-mcp')
            with patch.object(env, 'STATE', base / 'state'):
                env.write_json(env.project_state(project) / 'installed.json',
                               {'fingerprint': env.install_fingerprint(project, cfg),
                                'dependency_lock_sha256': env.digest(project / 'node_modules/.package-lock.json')})
                self.assertTrue(env.installed(project, cfg))
                (project / 'package-lock.json').write_text('{"changed":true}')
                self.assertFalse(env.installed(project, cfg))
                (project / 'package-lock.json').write_text('{}')
                (project / 'node_modules/.package-lock.json').unlink()
                self.assertFalse(env.installed(project, cfg))


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / 'app'
        self.project.mkdir()
        self.ledger = self.base / 'audit.json'
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.project / 'app.txt').write_text('baseline')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')
        chain.begin(self.project, 'Verify a representative change', self.ledger)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.project, check=True, capture_output=True)

    def claim(self, evidence, behavioral=False, status='verified'):
        data, _ = chain.load(self.ledger)
        data['claims'] = [{'id': 'behavior', 'statement': 'The intended contract holds',
                           'reasoning': 'Evidence directly exercises the stated property',
                           'behavioral': behavioral, 'status': status, 'files': ['app.txt'],
                           'chain': [{'layer': 'execution', 'finding': 'Observed result', 'evidence': evidence}]}]
        env.write_json(self.ledger, data)
        return data

    def test_file_evidence_and_changed_file_coverage(self):
        (self.project / 'app.txt').write_text('new content')
        chain.inspect_file(self.ledger, 'source', 'app.txt')
        result = chain.validate(self.claim(['source']), self.project)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['changed_files'], ['app.txt'])

    def test_uncovered_added_file_fails(self):
        chain.inspect_file(self.ledger, 'source', 'app.txt')
        (self.project / 'new.txt').write_text('new file')
        result = chain.validate(self.claim(['source']), self.project)
        self.assertIn('new.txt', result['changed_files'])
        self.assertEqual(result['status'], 'invalid')

    def test_deleted_file_must_be_accounted_for(self):
        (self.project / 'app.txt').unlink()
        data = self.claim([], status='out-of-scope')
        data['claims'][0]['files'] = []
        self.assertEqual(chain.validate(data, self.project)['status'], 'invalid')
        data['claims'][0]['files'] = ['app.txt']
        self.assertEqual(chain.validate(data, self.project)['status'], 'complete')

    def test_static_file_cannot_prove_behavior(self):
        chain.inspect_file(self.ledger, 'source', 'app.txt')
        self.assertEqual(chain.validate(self.claim(['source'], behavioral=True), self.project)['status'], 'invalid')

    def test_command_evidence_goes_stale_after_edit(self):
        self.assertEqual(chain.observe(self.ledger, 'test', [sys.executable, '-c', 'assert 2 + 2 == 4']), 0)
        data = self.claim(['test'], behavioral=True)
        self.assertEqual(chain.validate(data, self.project)['status'], 'complete')
        (self.project / 'app.txt').write_text('later edit')
        self.assertEqual(chain.validate(data, self.project)['status'], 'invalid')

    def test_command_changing_source_is_not_valid_final_evidence(self):
        chain.observe(self.ledger, 'test', [sys.executable, '-c',
                      'from pathlib import Path; Path("app.txt").write_text("changed")'])
        self.assertEqual(chain.validate(self.claim(['test'], behavioral=True), self.project)['status'], 'invalid')

    def test_failed_command_and_expected_rejection(self):
        self.assertEqual(chain.observe(self.ledger, 'rejection', [sys.executable, '-c', 'raise SystemExit(3)']), 3)
        data = self.claim(['rejection'], behavioral=True)
        self.assertEqual(chain.validate(data, self.project)['status'], 'invalid')
        data['claims'][0]['chain'][0]['expected_failure'] = True
        self.assertEqual(chain.validate(data, self.project)['status'], 'complete')

    def test_blocked_is_not_success(self):
        result = chain.validate(self.claim([], status='blocked'), self.project)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['blocked_claims'], ['behavior'])

    def test_external_evidence_needs_subject_and_timestamp(self):
        data = self.claim(['live'], behavioral=True)
        data['evidence']['live'] = {'kind': 'external', 'source': 'provider deployment API'}
        self.assertEqual(chain.validate(data, self.project)['status'], 'invalid')
        data['evidence']['live'].update(checked_at=chain.now(), subject='deployment-123', observation='healthy')
        self.assertEqual(chain.validate(data, self.project)['status'], 'complete')

    def test_file_evidence_rejects_outside_project(self):
        (self.base / 'outside.txt').write_text('outside')
        with self.assertRaises(env.EnvError):
            chain.inspect_file(self.ledger, 'outside', '../outside.txt')

    def test_begin_does_not_overwrite_or_write_inside_source(self):
        with self.assertRaises(env.EnvError):
            chain.begin(self.project, 'overwrite', self.ledger)
        with self.assertRaises(env.EnvError):
            chain.begin(self.project, 'self invalidation', self.project / 'audit.json')

    def test_retry_preserves_prior_evidence(self):
        chain.inspect_file(self.ledger, 'source', 'app.txt')
        with self.assertRaises(env.EnvError):
            chain.inspect_file(self.ledger, 'source', 'app.txt')

    def test_read_only_audit_still_needs_a_claim(self):
        data, _ = chain.load(self.ledger)
        self.assertEqual(chain.validate(data, self.project)['status'], 'invalid')


if __name__ == '__main__':
    unittest.main()
