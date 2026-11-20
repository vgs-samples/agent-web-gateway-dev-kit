"""Exercise the real shell dispatcher with synthetic process boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1]


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.env = {**os.environ, 'AWG_HOME': str(self.state), 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'FIXTURE_ROOT': str(self.root), 'CLOAKBROWSER_LICENSE_KEY': 'fixture-license'}

    def script(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\nset -eu\n' + body + '\n')
        path.chmod(0o700)
        return path

    def run_awg(self, *args):
        return subprocess.run(['/bin/bash', str(KIT / 'awg'), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_help_and_invalid_setup_do_not_install_anything(self):
        self.script('pyenv', 'echo unexpected-install >&2; exit 99')
        help_result = self.run_awg('--help')
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn('doctor', help_result.stdout)
        for args in [('setup', '--organization'), ('setup', '--from', 'old.env'), ('doctor',)]:
            result = self.run_awg(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('unexpected-install', result.stderr)

    def test_setup_uses_pyenv_not_path_vgs_and_forwards_choice(self):
        self.script('fixture-python', '''
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  cp "$FIXTURE_ROOT/bin/fixture-vgs" "$3/bin/vgs"
elif [ "${1:-}" = -m ] && [ "${2:-}" = pip ]; then
  printf '%s\\n' "$*" > "$FIXTURE_ROOT/pip-args"
else
  printf '%s\\n' "$@" > "$FIXTURE_ROOT/setup-args"
fi''')
        self.script('fixture-vgs', 'exit 0')
        self.script('vgs', 'echo wrong-vgs >&2; exit 98')
        self.script('pyenv', 'printf "%s\\n" "$*" >> "$FIXTURE_ROOT/pyenv-args"\nif [ "$1" = which ]; then printf "%s\\n" "$FIXTURE_ROOT/bin/fixture-python"; fi')
        result = self.run_awg('setup', '--organization', 'ACExample', '--tenant', 'tntSandbox')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('install -s 3.12.12', (self.root / 'pyenv-args').read_text())
        self.assertIn('vgs-cli==1.36.0', (self.root / 'pip-args').read_text())
        self.assertIn('--organization\nACExample\n--tenant\ntntSandbox', (self.root / 'setup-args').read_text())
        # Bash 3.2 + set -u also needs to handle no setup arguments.
        self.assertEqual(self.run_awg('setup').returncode, 0)

    def test_start_builds_session_and_cleans_up_helper(self):
        (self.state / 'sandbox.env').write_text('VGS_TENANT=tntFixture\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=fixture\n')
        # Curl never reaches a network. JSON fixtures model the actual API shapes.
        self.script('curl', '''
out=""
args="$*"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; out="$1"; fi
  shift
done
if [[ "$args" = *openid-connect/token* ]]; then
  printf '%s' '{"access_token":"fixture-token"}'
elif [[ "$args" = *sandbox.vgsapi.com/cards* ]]; then
  printf '%s' '{"data":{"id":"CRFixture","attributes":{"pan_alias":"tok_fixture_pan","cvc_alias":"tok_fixture_cvc","bin":"411111"}}}' > "$out"
  printf 201
elif [[ "$args" = *sandbox.vgsapi.com/reveal-sessions* ]]; then
  printf '%s' '{"data":{"id":"RSFixture","attributes":{"expires_at":"2099-01-01T00:00:00Z","allowed_hosts":["example.com"]}}}' > "$out"
  printf 201
else exit 94; fi''')
        self.script('uv', '''
args="$*"
if [[ "$args" = *start-proxy-controls.py* ]]; then
  echo $$ > "$FIXTURE_ROOT/helper-pid"
  echo 'Proxy controls are ready'
  exec sleep 15
elif [[ "$args" = *launch-panel.py* ]]; then
  printf '%s\\n' "$*" > "$FIXTURE_ROOT/browser-args"
else exit 93; fi''')
        result = self.run_awg('start', 'https://example.com/checkout')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Helper is running.', result.stdout)
        self.assertNotIn('fixture-token', result.stdout + result.stderr)
        self.assertTrue((self.state / 'sessions/RSFixture.json').exists())
        self.assertIn('https://example.com/checkout', (self.root / 'browser-args').read_text())
        pid = int((self.root / 'helper-pid').read_text())
        # The wrapper owns the helper for the lifetime of the browser.
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)


if __name__ == '__main__': unittest.main()
