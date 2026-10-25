"""Bounded invocation supervisor; survives the workflow controller exiting."""
import json
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def become_subreaper():
    """Adopt orphaned grandchildren, including children that call setsid()."""
    if not sys.platform.startswith('linux'):
        raise RuntimeError('the bounded worker requires Linux child-subreaper support')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'could not enable child subreaping')


def children():
    # /proc can be mounted from an ancestor PID namespace. Never compare its
    # host PIDs to os.getpid(), or pass those host IDs to namespace-local syscalls.
    status = Path('/proc/self/status').read_text().splitlines()
    own_ids = next(line.split()[1:] for line in status if line.startswith('NSpid:'))
    if int(own_ids[-1]) != os.getpid():
        raise RuntimeError('cannot map /proc PIDs into this process namespace')
    depth = len(own_ids) - 1
    direct = set()
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[1] != own_ids[0]:
                continue
            lines = (directory / 'status').read_text().splitlines()
            ids = next(line.split()[1:] for line in lines if line.startswith('NSpid:'))
            direct.add(int(ids[depth]))
        except (OSError, ValueError, IndexError, StopIteration):
            continue
    # Only signal our own unreaped direct children. Their PIDs cannot be reused
    # before this single-threaded supervisor reaps them. Killing them adopts
    # their children; subsequent passes clean those too.
    return direct


def cleanup_children():
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        descendants = children()
        if not descendants:
            return
        for pid in descendants:
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                finally:
                    os.close(descriptor)
            except ProcessLookupError:
                pass
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        time.sleep(.01)
    if children():
        raise RuntimeError('child cleanup did not finish within two seconds')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(directory):
    directory = Path(directory).resolve()
    request = json.loads((directory / 'request.json').read_text())
    timeout = max(0.01, request['deadline'] - time.time())
    report = directory / 'report.json'
    if request['backend'] == 'codex':
        argv = [request['executable'], '-a', 'never', 'exec', '--sandbox',
                'workspace-write' if request['role'] != 'reviewer' else 'read-only',
                '--json', '--output-schema', str(directory / 'schema.json'),
                '-o', str(report), '-']
        if request.get('model'):
            argv[-1:-1] = ['--model', request['model']]
        stdout_path = directory / 'events.jsonl'
    else:
        argv = [str(directory / 'request.json') if a == '{request}' else a
                for a in request['command']]
        stdout_path = report
    result = {'exit_code': None, 'timed_out': False, 'error': None}
    process = None
    try:
        become_subreaper()
        with stdout_path.open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(argv, cwd=request['workspace'],
                                       stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            try:
                process.communicate(request['prompt'].encode(), timeout=timeout)
                result['exit_code'] = process.returncode
            except subprocess.TimeoutExpired:
                result['timed_out'] = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        if process is not None:
            try:
                cleanup_children()
            except Exception as error:
                result['error'] = f'cleanup failed: {error}'
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                result['error'] = 'child did not terminate after cleanup'
    atomic_json(directory / 'exit.json', result)


if __name__ == '__main__':
    main(sys.argv[1])
