"""Run deterministic actors against a real defect; makes no model calls."""
import argparse
import json
from pathlib import Path
import sys

from .controller import Controller, git


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, help='New directory outside your project')
    parser.add_argument('--scenario', default='', help='Example: review:empty or verify:crash')
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'source'
    source.mkdir()
    git(source, 'init')
    (source / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
    (source / '.gitignore').write_text('__pycache__/\n')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Seed defect for deterministic feedback smoke test')
    fixture = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'loop_actor.py'
    config = dict(backend='command', commands={role: [sys.executable, str(fixture), '{request}', args.scenario]
                                             for role in ('builder', 'reviewer', 'verifier')},
                  timeout=10, check_timeout=10, max_attempts=3, max_remediations=4,
                  max_total_attempts=30,
                  check=[sys.executable, '-c', 'from calc import add; assert add(2,3) == 5; assert add(-3,1) == -2'])
    controller = Controller.create(root / 'state', source, 'Repair addition and independently verify it', config)
    try:
        state = controller.run()
        print(json.dumps({'kind': 'scripted subprocess demonstration; no LLM calls',
                          'state_directory': str(controller.root), 'status': state['status'],
                          'revision': state['revision'], 'attempts': state['total_attempts'],
                          'remediations': state['remediations'], 'diagnostic': state['diagnostic']}, indent=2))
        return 0 if state['status'] == 'complete' else 2
    finally:
        controller.close()


if __name__ == '__main__':
    raise SystemExit(main())
