"""Test-only Codex CLI contract shim. Does not call a model or Codex."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    argv = sys.argv[1:]
    if argv == ['login', 'status']:
        return 0
    if argv == ['--version']:
        print('test shim; not an installed Codex runtime')
        return 0
    assert argv[:3] == ['-a', 'never', 'exec'], argv
    assert argv[-1] == '-', argv
    assert argv[argv.index('--model') + 1] == 'fixture-model'
    report_path = Path(argv[argv.index('-o') + 1])
    request = json.loads(sys.stdin.read().split('Request identities, goal, baseline, feedback and acceptance command:\n', 1)[1])
    sandbox = argv[argv.index('--sandbox') + 1]
    assert sandbox == ('read-only' if request['role'] == 'reviewer' else 'workspace-write')
    schema_path = Path(argv[argv.index('--output-schema') + 1])
    assert 'attempt_id' in json.loads(schema_path.read_text())['required']
    fixture = Path(__file__).with_name('loop_actor.py')
    result = subprocess.run([sys.executable, str(fixture), str(report_path.parent / 'request.json')],
                            check=True, capture_output=True, text=True)
    report_path.write_text(result.stdout)
    print(json.dumps({'type': 'turn.completed', 'fixture_only': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
