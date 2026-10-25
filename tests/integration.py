"""Real Node/npm checks in a disposable Git repo; no application/API credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cloudenv


def run(command, cwd, success=True):
    result = subprocess.run(command, cwd=cwd)
    if (result.returncode == 0) != success:
        raise AssertionError(f'Unexpected exit {result.returncode}: {command}')


with tempfile.TemporaryDirectory(prefix='mcp-cloudenv-integration-') as temp:
    project = Path(temp)
    package = {
        'name': 'atproto-mcp', 'version': '0.0.0', 'private': True,
        'engines': {'node': '^24.22.1'},
        'scripts': {
            'types': 'node -e "console.log(process.version)"',
            'typecheck': 'node --check index.js',
            'test': 'node -e "if(require(\'./index.js\') !== 42) process.exit(1)"',
            'build': 'node -e "const fs=require(\'fs\'); fs.mkdirSync(\'dist\',{recursive:true}); fs.copyFileSync(\'index.js\',\'dist/index.js\')"',
        },
    }
    (project / 'package.json').write_text(json.dumps(package))
    (project / 'package-lock.json').write_text(json.dumps({
        'name': package['name'], 'version': '0.0.0', 'lockfileVersion': 3,
        'requires': True, 'packages': {'': {'name': package['name'], 'version': '0.0.0',
                                          'engines': package['engines']}}}))
    (project / 'index.js').write_text('module.exports = 42;\n')
    (project / '.gitignore').write_text('node_modules/\ndist/\n')
    run(['git', 'init', '-q'], project)
    run(['git', 'config', 'user.name', 'Environment Integration'], project)
    run(['git', 'config', 'user.email', 'integration@example.invalid'], project)
    run(['git', 'add', '.'], project)
    run(['git', 'commit', '-qm', 'fixture'], project)
    cli = [str(ROOT / 'bin/mcp-env')]
    def check(command, success=True, extra=()):
        run(cli + [command, '--project', str(project)] + list(extra), ROOT, success)
    check('doctor', False)
    check('prepare')
    check('doctor')
    check('verify')
    check('release-ready')
    (project / 'dist/index.js').write_text('changed artifact')
    check('release-ready', False)
    check('verify')
    (project / 'index.js').write_text('module.exports = 99;\n')
    check('release-ready', False)
    check('verify', False)
    (project / 'index.js').write_text('module.exports = 42;\n')
    check('release-ready', False)  # failure replaced the prior passing evidence
    check('verify')
    package['engines']['node'] = '>=99.0.0'
    (project / 'package.json').write_text(json.dumps(package))
    check('run', False, ('--', 'node', '--version'))
    # install must not accept an incompatible root package even with permissive user env.
    os.environ['npm_config_force'] = 'true'
    check('prepare', False)
    print('Integration checks passed: install, verify, stale source, build tampering, runtime rejection')
