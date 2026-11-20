"""Exercise the real shell dispatcher with synthetic process boundaries."""
import base64
import json
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
        self.script('uv', 'echo unexpected-install >&2; exit 99')
        help_result = self.run_awg('--help')
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn('doctor', help_result.stdout)
        for args in [('setup', '--organization'), ('setup', '--from', 'old.env'), ('doctor',)]:
            result = self.run_awg(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('unexpected-install', result.stderr)

    def test_setup_installs_cli_with_uv_not_path_vgs_and_forwards_choice(self):
        self.script('fixture-python', 'printf "%s\\n" "$@" > "$FIXTURE_ROOT/setup-args"')
        self.script('fixture-vgs', 'exit 0')
        self.script('vgs', 'echo wrong-vgs >&2; exit 98')
        # Nothing may be compiled: a pyenv on PATH must never be called.
        self.script('pyenv', 'echo unexpected-pyenv >&2; exit 99')
        self.script('uv', '''
printf '%s\\n' "$*" >> "$FIXTURE_ROOT/uv-args"
if [ "$1" = venv ]; then
  for last; do :; done
  mkdir -p "$last/bin"
  cp "$FIXTURE_ROOT/bin/fixture-python" "$last/bin/python"
elif [ "$1" = pip ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --python ]; then cp "$FIXTURE_ROOT/bin/fixture-vgs" "$(dirname "$2")/vgs"; fi
    shift
  done
else exit 93; fi''')
        result = self.run_awg('setup', '--organization', 'ACExample', '--tenant', 'tntSandbox')
        self.assertEqual(result.returncode, 0, result.stderr)
        uv_args = (self.root / 'uv-args').read_text()
        self.assertIn('venv --quiet --python 3.12', uv_args)
        self.assertIn('vgs-cli==1.37.0', uv_args)
        self.assertNotIn('unexpected-pyenv', result.stderr)
        self.assertIn('--organization\nACExample\n--tenant\ntntSandbox', (self.root / 'setup-args').read_text())
        # Bash 3.2 + set -u also needs to handle no setup arguments; the CLI is installed once.
        self.assertEqual(self.run_awg('setup').returncode, 0)
        self.assertEqual((self.root / 'uv-args').read_text(), uv_args)

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
        browser_args = (self.root / 'browser-args').read_text()
        self.assertIn('https://example.com/checkout', browser_args)
        # Each start loads the panel from its own folder, which is removed afterwards.
        self.assertIn('--extension ' + str(self.state / 'panel-extension') + '/', browser_args)
        self.assertFalse((self.state / 'panel-extension').exists())
        pid = int((self.root / 'helper-pid').read_text())
        # The wrapper owns the helper for the lifetime of the browser.
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_kernel_registers_the_session_as_a_proxy_and_cleans_up(self):
        (self.state / 'sandbox.env').write_text('VGS_TENANT=tntFixture\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=fixture\n')
        self.script('curl', '''
out=""
args="$*"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; out="$1"; fi
  shift
done
printf '%s\\n' "$args" | sed -E 's/Bearer [^ ]+/Bearer <key>/' >> "$FIXTURE_ROOT/calls"
if [[ "$args" = *openid-connect/token* ]]; then
  printf '%s' '{"access_token":"fixture-token"}'
elif [[ "$args" = *sandbox.vgsapi.com/cards* ]]; then
  printf '%s' '{"data":{"id":"CRFixture","attributes":{"pan_alias":"tok_fixture_pan","cvc_alias":"tok_fixture_cvc","bin":"411111"}}}' > "$out"
  printf 201
elif [[ "$args" = *sandbox.vgsapi.com/reveal-sessions* ]]; then
  printf '%s' '{"data":{"id":"RSFixture","attributes":{"expires_at":"2099-01-01T00:00:00Z","proxy":{"url":"https://US%40fixture:fixture-proxy-secret@tntFixture.sandbox.verygoodproxy.com:3443","ca_bundle":"-----BEGIN CERTIFICATE-----\\nfixture\\n-----END CERTIFICATE-----\\n","pac_url":"https://sandbox.vgsapi.com/reveal-sessions/RSFixture.pac"}}}}' > "$out"
  printf 201
elif [[ "$args" = *"-X POST https://api.onkernel.com/proxies"* ]]; then
  cat > "$FIXTURE_ROOT/proxy-body"
  printf '%s' '{"id":"proxy_fixture","type":"custom"}' > "$out"
  printf 201
elif [[ "$args" = *"-X POST https://api.onkernel.com/browsers"* ]]; then
  cat > "$FIXTURE_ROOT/browser-body"
  printf '%s' '{"session_id":"browser_fixture","browser_live_view_url":"https://live.example/fixture"}' > "$out"
  printf 201
elif [[ "$args" = *"-X GET https://api.onkernel.com/browsers/browser_fixture"* ]]; then
  printf 404
elif [[ "$args" = *"-X DELETE https://api.onkernel.com/"* ]]; then
  printf 204
else exit 94; fi''')
        missing = self.run_awg('kernel')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('KERNEL_API_KEY is not set', missing.stderr)
        self.assertFalse((self.root / 'calls').exists())

        self.env['KERNEL_API_KEY'] = 'fixture-kernel-key'
        result = self.run_awg('kernel', 'https://example.com/checkout')
        self.assertEqual(result.returncode, 0, result.stderr)
        proxy = json.loads((self.root / 'proxy-body').read_text())
        self.assertEqual(proxy['type'], 'custom')
        self.assertEqual(proxy['protocol'], 'https')
        self.assertEqual(proxy['config']['host'], 'tntFixture.sandbox.verygoodproxy.com')
        self.assertEqual(proxy['config']['port'], 3443)
        self.assertEqual(proxy['config']['username'], 'US@fixture')
        self.assertEqual(proxy['config']['password'], 'fixture-proxy-secret')
        self.assertIn('BEGIN CERTIFICATE', proxy['config']['ca_bundle'])
        browser = json.loads((self.root / 'browser-body').read_text())
        self.assertEqual(browser['proxy'], {'id': 'proxy_fixture'})
        self.assertEqual(browser['start_url'], 'https://example.com/checkout')
        self.assertIn('https://live.example/fixture', result.stdout)
        self.assertIn('Kernel browser session: browser_fixture', result.stdout)
        self.assertIn('Kernel proxy: proxy_fixture', result.stdout)
        # Secrets stay out of the output and off the command line; the proxy and browser are removed.
        calls = (self.root / 'calls').read_text()
        for secret in ('fixture-kernel-key', 'fixture-proxy-secret'):
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertNotIn('fixture-proxy-secret', calls)
        self.assertIn('-X DELETE https://api.onkernel.com/browsers/browser_fixture', calls)
        self.assertIn('-X DELETE https://api.onkernel.com/proxies/proxy_fixture', calls)
        self.assertEqual(list(self.state.glob('kernel.*')), [])

    def test_session_uses_alias_api_when_cards_api_refuses(self):
        (self.state / 'sandbox.env').write_text('VGS_TENANT=tntFixture\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=fixture\n')
        # Token payload: {"scope":"aliases:write reveal-sessions:write"} - no card scope.
        self.script('curl', '''
out=""
args="$*"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; out="$1"; fi
  shift
done
if [[ "$args" = *openid-connect/token* ]]; then
  printf '%s' '{"access_token":"e30.eyJzY29wZSI6ImFsaWFzZXM6d3JpdGUgcmV2ZWFsLXNlc3Npb25zOndyaXRlIn0.sig"}'
elif [[ "$args" = *sandbox.vgsapi.com/cards* ]]; then
  printf '%s' '{"errors":[{"status":"403","title":"Forbidden"}]}' > "$out"
  printf 403
elif [[ "$args" = *tntFixture.sandbox.vault-api.verygoodvault.com/aliases* ]]; then
  printf '%s' '{"data":[{"aliases":[{"alias":"tok_fixture_pan","format":"UUID"}]},{"aliases":[{"alias":"tok_fixture_cvc","format":"UUID"}]}]}' > "$out"
  printf 201
elif [[ "$args" = *sandbox.vgsapi.com/reveal-sessions* ]]; then
  printf '%s' "$args" > "$FIXTURE_ROOT/session-request"
  printf '%s' '{"data":{"id":"RSFixture","attributes":{"expires_at":"2099-01-01T00:00:00Z"}}}' > "$out"
  printf 201
else exit 94; fi''')
        result = self.run_awg('session')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('HTTP 403', result.stdout)
        self.assertIn('created without cards:create', result.stdout)
        # The success line comes first, so the 403 does not read as a failure.
        self.assertLess(result.stdout.index('through the alias API'), result.stdout.index('HTTP 403'))
        # The Cards API can be skipped outright.
        skipped = subprocess.run(['/bin/bash', str(KIT / 'awg'), 'session'], env={**self.env, 'AWG_CARD_STORE': 'aliases'},
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(skipped.returncode, 0, skipped.stderr)
        self.assertIn('through the alias API', skipped.stdout)
        self.assertNotIn('HTTP 403', skipped.stdout)
        # An account the kit did not create is told what it lacks before anything is refused.
        note = result.stdout.split('Note: this service account lacks: ')[1].splitlines()[0]
        self.assertIn('cards:create', note)
        self.assertIn('agent-gateway:read', note)
        self.assertNotIn('aliases:write', note)
        self.assertLess(result.stdout.index('Note:'), result.stdout.index('HTTP 403'))
        request = (self.root / 'session-request').read_text()
        self.assertIn('tok_fixture_pan', request)
        self.assertIn('tok_fixture_cvc', request)

    def test_scope_granted_as_a_role_but_absent_from_the_token_is_reported_as_such(self):
        (self.state / 'sandbox.env').write_text('VGS_TENANT=tntFixture\nVGS_CLIENT_ID=fixture\nVGS_CLIENT_SECRET=fixture\n')
        every = ['cards:create', 'cards:read', 'cards:update', 'aliases:write', 'reveal-sessions:read',
                 'reveal-sessions:write', 'agent-gateway:read', 'agent-gateway:write']
        # All eight are roles; the scope claim, which the APIs read, omits two.
        claims = {'scope': ' '.join(s for s in every if s not in ('cards:create', 'cards:update')),
                  'resource_access': {'fixture': {'roles': every}}}
        token = 'e30.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.sig'
        self.script('curl', '''
out=""
args="$*"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; out="$1"; fi
  shift
done
if [[ "$args" = *openid-connect/token* ]]; then
  printf '%s' '{"access_token":"''' + token + '''"}'
elif [[ "$args" = *sandbox.vgsapi.com/cards* ]]; then
  printf '%s' '{"errors":[{"status":"403"}]}' > "$out"
  printf 403
elif [[ "$args" = *vault-api.verygoodvault.com/aliases* ]]; then
  printf '%s' '{"data":[{"aliases":[{"alias":"tok_fixture_pan","format":"UUID"}]},{"aliases":[{"alias":"tok_fixture_cvc","format":"UUID"}]}]}' > "$out"
  printf 201
elif [[ "$args" = *sandbox.vgsapi.com/reveal-sessions* ]]; then
  printf '%s' '{"data":{"id":"RSFixture","attributes":{"expires_at":"2099-01-01T00:00:00Z"}}}' > "$out"
  printf 201
else exit 94; fi''')
        result = self.run_awg('session')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('was granted cards:create, cards:update, but VGS leaves them out of its access token', result.stdout)
        self.assertNotIn('service account lacks', result.stdout)
        self.assertNotIn('setup --force', result.stdout)
        self.assertIn('its access token does not carry it', result.stdout)


if __name__ == '__main__': unittest.main()
