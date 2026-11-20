#!/usr/bin/env python3
"""Run an assertion-bearing case in pinned native Larky with networking disabled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

PIN = '9a2d9f179984f2e019132e04e9fdc5d17e21d1f1e9cd12581018519acf7f34b3'
IMAGE = 'debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--result-dir', type=Path, required=True, help='New private directory')
    parser.add_argument('--source', type=Path, help='Exact deployment source for manifest hash')
    parser.add_argument('--expected-error', help='Required runtime error text for a negative case')
    parser.add_argument('--timeout', type=int, default=35)
    args = parser.parse_args()
    os.umask(0o077)
    runtime, case, output = (p.resolve() for p in (args.runtime_dir, args.case_dir, args.result_dir))
    if args.timeout < 1 or args.timeout > 300:
        parser.error('--timeout must be 1–300 seconds')
    if any(',' in str(p) for p in (runtime, case, output)):
        parser.error('Docker bind paths must not contain commas')
    if digest(runtime / 'larky-1.0.0-linux') != PIN:
        parser.error('Larky checksum mismatch; do not update the pin silently')
    report = {'runtime': 'official native Larky 1.0.0 Linux amd64', 'binarySha256': PIN,
              'dockerImage': IMAGE, 'network': 'none', 'inputSha256': digest(case / 'input.star'),
              'testSha256': digest(case / 'test.star'),
              'scope': 'Local case execution only; source hash does not prove harness equivalence or deployment readiness.'}
    if args.source:
        report['sourceSha256'] = digest(args.source)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    name = 'skill-larky-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--pull=never', '--name', name,
               '--platform', 'linux/amd64', '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '64', '--memory', '512m', '--cpus', '1',
               '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
               '--mount', f'type=bind,source={runtime},target=/runtime,readonly',
               '--mount', f'type=bind,source={case},target=/work,readonly',
               '--mount', f'type=bind,source={output},target=/results', IMAGE,
               '/runtime/larky-1.0.0-linux', '-i', '/work/input.star', '-s', '/work/test.star',
               '-o', '/results/output.txt', '-l', '/results/run.log']
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
        log = run.stdout + run.stderr
        report['exitCode'] = run.returncode
        if args.expected_error:
            report['expectedError'] = args.expected_error
            report['passed'] = (run.returncode not in (0, 125, 126, 127)
                                and args.expected_error in log
                                and 'EXPECTED_ERROR_NOT_RAISED' not in log)
        else:
            report['passed'] = run.returncode == 0 and 'LARKY_CASE_PASSED' in log
    except subprocess.TimeoutExpired:
        cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, text=True, timeout=10)
        log = 'Native Larky case timed out.\n'
        report.update(passed=False, timedOut=True, cleanupExitCode=cleanup.returncode)
    except OSError as error:
        log = str(error) + '\n'
        report.update(passed=False, runnerError=type(error).__name__)
    (output / 'console.log').write_text(log)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(('PASS' if report['passed'] else 'FAIL') + ': ' + str(output / 'report.json'))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
