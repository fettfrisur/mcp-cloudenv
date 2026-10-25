"""Scripted actor for deterministic fault injection. This is NOT an LLM."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

request = json.loads(Path(sys.argv[1]).read_text())
scenario = sys.argv[2] if len(sys.argv) > 2 else ''
stage = request['stage']
report = {k: request[k] for k in ('run_id', 'attempt_id', 'stage', 'role', 'input_revision')}
report.update(version=1, summary='The scripted fixture inspected the requested source files.',
              verdict='ready' if request['role'] == 'builder' else 'pass', findings=[],
              evidence=[{'path': 'PLAN.md' if stage in ('plan', 'plan_review') else 'calc.py',
                         'detail': 'Inspected the actual source file in this checkout.'}])

faults = scenario.split(':')
if len(faults) >= 2 and faults[0] == stage and (request['number'] == 1 or len(faults) == 3):
    fault = faults[1]
    if fault == 'empty':
        sys.exit(0)
    if fault == 'garbage':
        print('the moon dances loudly, therefore success!')
        sys.exit(0)
    if fault == 'crash':
        os.kill(os.getpid(), signal.SIGKILL)
    if fault == 'hang':
        time.sleep(60)
    if fault == 'wrong':
        report['input_revision'] = 'obsolete'
    if fault == 'edit':
        Path('calc.py').write_text('corrupted by reviewer\n')
    if fault == 'escape':
        report['evidence'][0]['path'] = '/etc/passwd'
    if fault == 'missing':
        report['evidence'][0]['path'] = 'absent.py'
    if fault == 'large':
        report['summary'] = 'X' * 140000
    if fault == 'blocked':
        report['verdict'] = 'blocked'
        report['summary'] = 'Required external service is unavailable; human access is needed.'
    if fault == 'background':
        subprocess.Popen([sys.executable, '-c',
                          "import time; from pathlib import Path; time.sleep(.2); Path('calc.py').write_text('late damage')"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def reject(identity, detail):
    report.update(verdict='changes_requested', findings=[{'id': identity, 'detail': detail}])


if stage == 'plan':
    Path('PLAN.md').write_text('Implement addition; test add(2, 3) == 5, including negative operands.\n')
if stage == 'plan_review' and scenario == 'plan-reject':
    if not any(f['stage'] == 'plan_review' for f in request['feedback']):
        reject('plan-gap', 'The plan needs an independently executed acceptance command.')
if stage == 'build' and any(f['stage'] != 'plan_review' and f['report']['findings'] for f in request['feedback']):
    Path('calc.py').write_text('def add(a, b):\n    return a + b\n')
if stage == 'review' and report['verdict'] != 'blocked' and scenario != 'check-catches' and 'a - b' in Path('calc.py').read_text():
    reject('wrong-operation', 'add(2, 3) returns -1 rather than 5; implement addition.')
if stage == 'branch_review' and scenario == 'branch-reject' and not any(f['stage'] == stage for f in request['feedback']):
    reject('branch-gap', 'Add explicit independent verification of the full accumulated revision.')
print(json.dumps(report))
