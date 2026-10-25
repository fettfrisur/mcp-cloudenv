#!/usr/bin/env python3
"""Repository-owned tooling for Codex Cloud. Python standard library only."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.cloudenv'


class EnvError(Exception):
    pass


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def version(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise EnvError(f'Expected a stable exact version, got {value!r}')
    return tuple(map(int, value.lstrip('v').split('.')))


def policy():
    result = read_json(ROOT / 'policy.json')
    node = result['node']
    if result['schema'] != 1 or version(node['version'])[0] != node['major']:
        raise EnvError('Invalid runtime policy')
    if any(not re.fullmatch('[0-9a-f]{64}', h) for h in node['sha256'].values()):
        raise EnvError('Invalid archive digest')
    if sys.version_info[:2] < tuple(result['python_minimum']):
        raise EnvError('Python 3.12+ is required for safe archive extraction')
    return result


def machine_key():
    arch = {'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or not arch:
        raise EnvError('Managed toolchain supports Linux x64/arm64 only')
    return f'linux-{arch}'


def toolchain_dir():
    return STATE / 'toolchains' / f"node-v{policy()['node']['version']}-{machine_key()}"


def fetch(url):
    # urllib respects the environment's HTTPS proxy and certificate configuration.
    request = urllib.request.Request(url, headers={'User-Agent': 'mcp-cloudenv/1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith('https://'):
            raise EnvError('Refusing a non-HTTPS redirect')
        return response.read()


def capture(argv, cwd=None, env=None):
    return subprocess.check_output(argv, cwd=cwd, env=env, text=True, stderr=subprocess.PIPE).strip()


def managed_env():
    destination = toolchain_dir()
    receipt = destination / '.receipt.json'
    if not receipt.exists():
        raise EnvError('Managed Node is missing; run bin/mcp-env bootstrap')
    saved = read_json(receipt)
    expected = policy()['node']
    if saved['archive_sha256'] != expected['sha256'][machine_key()]:
        raise EnvError('Toolchain receipt differs from policy; rebuild toolchain')
    if digest(destination / 'bin/node') != saved['node_sha256']:
        raise EnvError('Managed Node binary changed; rebuild toolchain')
    env = os.environ.copy()
    env['PATH'] = str(destination / 'bin') + os.pathsep + env.get('PATH', '')
    # Enforce installation policy, even if the caller has a permissive user config.
    env['npm_config_engine_strict'] = 'true'
    env['npm_config_force'] = 'false'
    env['WRANGLER_SEND_METRICS'] = 'false'
    actual = capture([str(destination / 'bin/node'), '--version'], env=env)
    if actual != 'v' + expected['version']:
        raise EnvError(f'Expected Node {expected["version"]}, found {actual}')
    return env


def bootstrap():
    destination = toolchain_dir()
    if destination.exists():
        managed_env()
        print(f'Toolchain already verified: {destination}')
        return
    cfg = policy()['node']
    archive_name = destination.name + '.tar.xz'
    data = fetch(f'https://nodejs.org/dist/v{cfg["version"]}/{archive_name}')
    expected = cfg['sha256'][machine_key()]
    if hashlib.sha256(data).hexdigest() != expected:
        raise EnvError('Node archive checksum mismatch; nothing installed')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        archive = Path(temp) / archive_name
        archive.write_bytes(data)
        with tarfile.open(archive, 'r:xz') as tar:
            tar.extractall(Path(temp) / 'unpacked', filter='data')
        unpacked = Path(temp) / 'unpacked' / destination.name
        write_json(unpacked / '.receipt.json', {
            'archive_sha256': expected, 'node_sha256': digest(unpacked / 'bin/node')})
        unpacked.rename(destination)
    managed_env()
    print(f'Installed and verified Node {cfg["version"]}: {destination}')


def profile(name):
    if not re.fullmatch('[a-z0-9-]+', name):
        raise EnvError('Invalid profile name')
    return read_json(ROOT / 'profiles' / f'{name}.json')


def project_path(value, cfg):
    project = Path(value).resolve()
    package = read_json(project / 'package.json')
    if package.get('name') != cfg['package_name']:
        raise EnvError(f'Expected package {cfg["package_name"]}, got {package.get("name")}')
    if not (project / 'package-lock.json').is_file():
        raise EnvError('A committed npm lockfile is required')
    return project


def project_state(project):
    key = hashlib.sha256(str(project).encode()).hexdigest()[:20]
    return STATE / 'projects' / key


def install_fingerprint(project, cfg):
    values = {name: digest(project / name) if (project / name).exists() else None
              for name in cfg['install_inputs']}
    values['policy'] = policy()
    values['profile'] = cfg
    values['platform'] = machine_key()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def installed(project, cfg):
    stamp = project_state(project) / 'installed.json'
    if not stamp.exists():
        return False
    lock = project / 'node_modules/.package-lock.json'
    # npm does not create node_modules for a dependency-free project.
    if len(read_json(project / 'package-lock.json').get('packages', {})) > 1 and not lock.is_file():
        return False
    saved = read_json(stamp)
    return (saved.get('fingerprint') == install_fingerprint(project, cfg)
            and saved.get('dependency_lock_sha256') == (digest(lock) if lock.is_file() else None))


def prepare(project, cfg):
    env = managed_env()
    if installed(project, cfg):
        print('Dependencies match the current lockfile and runtime policy')
        return
    stamp = project_state(project) / 'installed.json'
    stamp.unlink(missing_ok=True)
    subprocess.run(['npm', 'ci', '--engine-strict'], cwd=project, env=env, check=True)
    lock = project / 'node_modules/.package-lock.json'
    write_json(stamp, {'fingerprint': install_fingerprint(project, cfg),
                       'dependency_lock_sha256': digest(lock) if lock.is_file() else None})
    print('Dependency installation recorded; run verify before claiming readiness')


def require_fresh(project, cfg):
    if not installed(project, cfg):
        raise EnvError('Dependency state is stale or missing; run prepare for this project')


def source_state(project):
    head = capture(['git', 'rev-parse', 'HEAD'], cwd=project)
    status = capture(['git', 'status', '--porcelain=v1'], cwd=project)
    files = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard'], cwd=project).decode()
    hashes = {}
    for name in sorted(set(files.split('\0')) - {''}):
        path = project / name
        if path.is_symlink():
            hashes[name] = hashlib.sha256(os.readlink(path).encode()).hexdigest()
        elif path.is_file():
            hashes[name] = digest(path)
        else:
            hashes[name] = None
    source_digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {'commit': head, 'dirty': bool(status), 'source_sha256': source_digest}


def build_hashes(project, cfg):
    build = project / cfg['build_directory']
    return {str(p.relative_to(project)): digest(p) for p in sorted(build.rglob('*'))
            if p.is_file() and not p.is_symlink()} if build.is_dir() else {}


def verify(project, cfg):
    env = managed_env()
    require_fresh(project, cfg)
    package = read_json(project / 'package.json')
    scripts = package.get('scripts', {})
    missing = [name for name in cfg['required_scripts'] if name not in scripts]
    if missing:
        raise EnvError(f'Missing mandatory verification scripts: {missing}')
    initial = source_state(project)
    result = {
        'schema': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
        'project': str(project), 'source': initial,
        'environment_commit': capture(['git', 'rev-parse', 'HEAD'], cwd=ROOT),
        'environment_source': source_state(ROOT),
        'policy_sha256': digest(ROOT / 'policy.json'),
        'runner_sha256': digest(Path(__file__)),
        'install_fingerprint': install_fingerprint(project, cfg),
        'node': capture(['node', '--version'], env=env),
        'npm': capture(['npm', '--version'], env=env),
        'python': platform.python_version(), 'platform': platform.platform(),
        'checks': [], 'passed': False,
        'paid_evaluations': 'not-run', 'deployment': 'not-run',
        'optional_absent': [s for s in cfg['optional_scripts'] if s not in scripts],
    }
    evidence = project_state(project) / 'verification.json'
    write_json(evidence, result)  # A failed/interrupted attempt invalidates an older success.
    for script in cfg['required_scripts'] + [s for s in cfg['optional_scripts'] if s in scripts]:
        start = time.monotonic()
        command = ['npm', 'run', script]
        code = subprocess.run(command, cwd=project, env=env).returncode
        result['checks'].append({'command': command, 'exit_code': code,
                                 'seconds': round(time.monotonic() - start, 3)})
        write_json(evidence, result)
        if code:
            raise EnvError(f'{script} failed ({code}); evidence: {evidence}')
    result['artifacts'] = build_hashes(project, cfg)
    result['passed'] = (source_state(project) == initial
                        and source_state(ROOT) == result['environment_source'])
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_json(evidence, result)
    if not result['passed']:
        raise EnvError('Application or environment source changed during verification; review and rerun')
    print(f'Checks passed; evidence: {evidence}')


def release_ready(project, cfg):
    managed_env()
    require_fresh(project, cfg)
    evidence = project_state(project) / 'verification.json'
    if not evidence.exists():
        raise EnvError('No verification evidence')
    result = read_json(evidence)
    current = source_state(project)
    environment_source = source_state(ROOT)
    if current['dirty'] or environment_source['dirty']:
        raise EnvError('Release requires clean committed application and environment trees')
    if (not result['passed'] or result['source'] != current
            or result['policy_sha256'] != digest(ROOT / 'policy.json')
            or result['runner_sha256'] != digest(Path(__file__))
            or result['install_fingerprint'] != install_fingerprint(project, cfg)
            or result.get('environment_source') != environment_source
            or result['environment_commit'] != capture(['git', 'rev-parse', 'HEAD'], cwd=ROOT)):
        raise EnvError('Verification is failed or stale; rerun verify on the committed tree')
    if not result.get('artifacts') or result['artifacts'] != build_hashes(project, cfg):
        raise EnvError('Build artifacts are absent or changed; rerun verify')
    print('Local release prerequisites pass. No deployment was performed.')
    print(f'Use {evidence} for the authorized release and post-deployment record.')


def doctor(project, cfg):
    env = managed_env()
    package = read_json(project / 'package.json')
    lock = read_json(project / 'package-lock.json')
    print(json.dumps({
        'managed_node': capture(['node', '--version'], env=env),
        'managed_npm': capture(['npm', '--version'], env=env),
        'dependencies_fresh': installed(project, cfg),
        'package_engine': package.get('engines', {}).get('node'),
        'lock_engine': lock.get('packages', {}).get('', {}).get('engines', {}).get('node'),
        'dev_engines': package.get('devEngines'),
        'version_files': {name: (project / name).read_text().strip()
                          for name in ['.nvmrc', '.node-version'] if (project / name).exists()},
        'scope': 'Wrapper enforcement only; target CI/direct commands require adoption',
    }, indent=2))
    require_fresh(project, cfg)


def choose_candidate(releases, cfg):
    candidates = [r for r in releases if re.fullmatch(r'v\d+\.\d+\.\d+', r.get('version', ''))
                  and version(r['version'])[0] == cfg['node']['major']]
    if not candidates:
        raise EnvError('Release feed has no entries for the supported Node major')
    return max(candidates, key=lambda r: version(r['version']))


def updates(output):
    cfg = policy()
    latest = choose_candidate(json.loads(fetch('https://nodejs.org/dist/index.json')), cfg)
    current = cfg['node']['version']
    newer = version(latest['version']) > version(current)
    age = (date.today() - date.fromisoformat(cfg['node']['reviewed_on'])).days
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'current': current,
              'latest_in_supported_major': latest['version'], 'newer_available': newer,
              'review_due': age > cfg['review_interval_days'],
              'release_url': 'https://nodejs.org/en/blog/release/' + latest['version'],
              'next_action': 'Review release notes, update pin/digests, run checks, republish Cloud setup'}
    if output:
        write_json(output, result)
    print(json.dumps(result, indent=2))
    if newer or result['review_due']:
        raise EnvError('Runtime maintenance is due; see the update report')


def audit(project, cfg):
    env = managed_env()
    require_fresh(project, cfg)
    # npm audit reports dependencies, not Node itself or the Workers runtime.
    code = subprocess.run(['npm', 'audit', '--audit-level=high'], cwd=project, env=env).returncode
    if code:
        raise EnvError('Dependency audit failed or was unavailable; inspect npm output')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['bootstrap', 'prepare', 'doctor', 'verify',
                                          'release-ready', 'run', 'updates', 'audit'])
    parser.add_argument('--project', help='Explicit path to the application checkout')
    parser.add_argument('--profile', default='atproto-mcp')
    parser.add_argument('--output', help='JSON report path (updates only)')
    # Parse command arguments after -- separately, without shell interpretation.
    arguments = sys.argv[1:]
    extra = []
    if '--' in arguments:
        split = arguments.index('--')
        arguments, extra = arguments[:split], arguments[split + 1:]
    args = parser.parse_args(arguments)
    policy()
    if args.command == 'bootstrap':
        bootstrap()
    elif args.command == 'updates':
        updates(args.output)
    else:
        if not args.project:
            parser.error('--project is required')
        cfg = profile(args.profile)
        project = project_path(args.project, cfg)
        if args.command == 'run':
            env = managed_env()
            require_fresh(project, cfg)
            if not extra:
                parser.error('run requires a command after --')
            # A convenience command runner, not a sandbox or a shell interception layer.
            raise SystemExit(subprocess.run(extra, cwd=project, env=env).returncode)
        else:
            {'prepare': prepare, 'doctor': doctor, 'verify': verify,
             'release-ready': release_ready, 'audit': audit}[args.command](project, cfg)


if __name__ == '__main__':
    try:
        main()
    except (EnvError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'mcp-env: {error}', file=sys.stderr)
        sys.exit(1)
