"""Offline onboarding tests: no VGS login, credentials, or network needed."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

KIT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', KIT / 'tools/bootstrap/setup.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def tenant(identifier='tntSandbox', organization='ACExample', environment='SANDBOX', name='Test'):
    return {'attributes': {'identifier': identifier, 'environment': environment, 'name': name},
            'relationships': {'organization': {'data': {'id': organization}}}}


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, self.previous_umask)
        self.calls = []
        self.organizations = {'data': [{'id': 'ACExample', 'attributes': {'name': 'Example'}}]}
        self.tenants = {'data': [tenant(), tenant('tntLive', environment='LIVE')]}
        self.fail_apply = False
        owner = self

        class FakeCLI:
            def __init__(self, executable, directory): self.directory = directory
            def login(self): owner.calls.append(['login'])
            def run(self, args, filename):
                owner.calls.append(args)
                if args == ['get', 'organizations']: value = owner.organizations
                elif args == ['get', 'tenants']: value = owner.tenants
                elif args[:2] == ['generate', 'service-account']:
                    value = {'apiVersion': '1.0.0', 'kind': 'ServiceAccount', 'data': {'scopes': [{'name': 'vaults:write'}]}}
                elif args[:2] == ['apply', 'service-account']:
                    value = yaml.safe_load(Path(args[-1]).read_text())
                    owner.applied = value
                    if owner.fail_apply:
                        raise (bootstrap.SetupError if owner.fail_apply is True else owner.fail_apply)('synthetic failed creation')
                    value['data'].update(clientId='fixture-client', clientSecret='fixture-secret-never-print')
                else: raise AssertionError(args)
                output = self.directory / filename
                output.write_text(yaml.safe_dump(value))
                return output

        self.cli_patch = patch.object(bootstrap, 'CLI', FakeCLI)
        self.cli_patch.start()
        self.addCleanup(self.cli_patch.stop)
        self.verify = patch.object(bootstrap, 'verify').start()
        self.addCleanup(patch.stopall)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def run_setup(self, **kwargs):
        bootstrap.onboard(self.state, '/fake/vgs', **kwargs)

    def test_confirms_even_one_organization(self):
        answers = []
        choice = bootstrap.choose_organization(self.organizations, prompt=lambda q: answers.append(q) or 'ACExample')
        self.assertEqual(choice, 'ACExample')
        self.assertEqual(len(answers), 1)
        with self.assertRaises(bootstrap.SetupError):
            bootstrap.choose_organization(self.organizations, 'ACWrong')

    def test_filters_tenants_and_selects_deterministically(self):
        choices = {'data': [tenant('tntA', organization='ACOther'), tenant('tntB', environment='LIVE'),
                            tenant('tntZ'), tenant('tntC')]}
        self.assertEqual(bootstrap.choose_tenant(choices, 'ACExample'), 'tntC')
        choices['data'].append(tenant('tntDedicated', name='Agent Web Gateway Dev Kit'))
        self.assertEqual(bootstrap.choose_tenant(choices, 'ACExample'), 'tntDedicated')
        self.assertEqual(bootstrap.choose_tenant(choices, 'ACExample', 'tntZ'), 'tntZ')
        for wrong in ('tntA', 'tntB', 'tntMissing'):
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.choose_tenant(choices, 'ACExample', wrong)

    def test_login_create_verify_save_and_reuse(self):
        self.run_setup(organization='ACExample')
        self.assertEqual(self.calls[0], ['login'])
        self.assertEqual(self.applied['data']['vaults'], ['tntSandbox'])
        scopes = {x['name'] for x in self.applied['data']['scopes']}
        self.assertEqual(scopes, set(bootstrap.SCOPES))
        self.assertLessEqual(len(self.applied['data']['name']), 20)
        self.assertNotIn('vaults:write', scopes)
        self.assertNotIn('cards:read-pci', scopes)
        credentials = self.state / 'sandbox.env'
        self.assertIn('VGS_TENANT=tntSandbox', credentials.read_text())
        self.assertNotIn('fixture-secret-never-print', self.output.getvalue())
        for path in self.state.rglob('*'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        count = len(self.calls)
        self.run_setup()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.verify.call_count, 2)

    def test_rejects_wrong_org_or_live_before_creation(self):
        for kwargs in ({'organization': 'ACWrong'}, {'organization': 'ACExample', 'tenant': 'tntLive'}):
            with self.assertRaises(bootstrap.SetupError): self.run_setup(**kwargs)
        self.assertFalse(any(c[0] == 'apply' for c in self.calls))
        self.assertFalse((self.state / 'sandbox.env').exists())

    def test_verification_failure_resumes_without_duplicate_or_overwrite(self):
        old = 'VGS_TENANT=tntOld\nVGS_CLIENT_ID=old\nVGS_CLIENT_SECRET=old\n'
        (self.state / 'sandbox.env').write_text(old)
        self.verify.side_effect = bootstrap.SetupError('synthetic access failure')
        with self.assertRaises(bootstrap.SetupError): self.run_setup(organization='ACExample', force=True)
        self.assertEqual((self.state / 'sandbox.env').read_text(), old)
        self.assertTrue((self.state / 'setup-pending.json').exists())
        calls = len(self.calls)
        self.verify.side_effect = None
        self.run_setup()
        self.assertEqual(len(self.calls), calls)
        self.assertIn('tntSandbox', (self.state / 'sandbox.env').read_text())
        self.assertFalse((self.state / 'setup-pending.json').exists())

    def test_interrupted_apply_starts_again_and_names_the_unused_account(self):
        self.fail_apply = True
        with self.assertRaises(bootstrap.SetupError): self.run_setup(organization='ACExample')
        name = self.applied['data']['name']
        self.fail_apply = False
        self.run_setup()
        self.assertIn(name, self.output.getvalue())
        self.assertNotEqual(self.applied['data']['name'], name)
        self.assertIn('tntSandbox', (self.state / 'sandbox.env').read_text())
        self.assertFalse((self.state / 'setup-pending.json').exists())

    def test_output_saved_before_an_interruption_is_reused(self):
        self.fail_apply = True
        with self.assertRaises(bootstrap.SetupError): self.run_setup(organization='ACExample')
        attempt = json.loads((self.state / 'setup-pending.json').read_text())
        self.applied['data'].update(clientId='fixture-client', clientSecret='fixture-secret-never-print')
        (Path(attempt['directory']) / 'apply-output.yaml').write_text(yaml.safe_dump(self.applied))
        count = len(self.calls)
        self.run_setup()
        self.assertEqual(len(self.calls), count)
        self.assertIn('VGS_CLIENT_ID=fixture-client', (self.state / 'sandbox.env').read_text())

    def test_rejected_apply_can_be_retried(self):
        self.fail_apply = bootstrap.CLIRejected
        with self.assertRaises(bootstrap.SetupError): self.run_setup(organization='ACExample')
        self.assertFalse((self.state / 'setup-pending.json').exists())
        self.fail_apply = False
        self.run_setup(organization='ACExample')
        self.assertIn('tntSandbox', (self.state / 'sandbox.env').read_text())

    def test_attempt_rejected_by_an_older_kit_is_not_stuck(self):
        # Older kits left the marker behind when VGS refused the 24-character account name.
        earlier = self.state / 'setup' / 'earlier'
        earlier.mkdir(parents=True)
        (earlier / 'apply-output.yaml').write_text('')
        (earlier / 'apply-output.yaml.stderr').write_text('name too long')
        (self.state / 'setup-pending.json').write_text(
            json.dumps({'organization': 'ACExample', 'tenant': 'tntSandbox', 'directory': str(earlier)}))
        self.run_setup()
        self.assertIn('tntSandbox', (self.state / 'sandbox.env').read_text())
        self.assertFalse((self.state / 'setup-pending.json').exists())

    def test_new_selection_requires_force(self):
        self.run_setup(organization='ACExample')
        with self.assertRaises(bootstrap.SetupError): self.run_setup(organization='ACOther')

    def test_invalid_or_multiline_credentials_are_rejected(self):
        for data in ({}, {'vaults': ['tntSandbox'], 'clientId': 'fixture', 'clientSecret': 'bad\nline'},
                     {'vaults': ['tntOther'], 'clientId': 'fixture', 'clientSecret': 'fixture'}):
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.credentials_from_result({'kind': 'ServiceAccount', 'data': data}, 'tntSandbox')


class ExternalBoundaryTests(unittest.TestCase):
    def test_cli_captures_both_streams_and_removes_inherited_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'VGS_CLIENT_ID': 'do-not-use', 'VGS_CLIENT_SECRET': 'do-not-use'}):
                cli = bootstrap.CLI('/fixture/vgs', Path(tmp))
            def execute(args, **kwargs):
                self.assertNotIn('VGS_CLIENT_SECRET', kwargs['env'])
                self.assertNotIn('VGS_CLIENT_ID', kwargs['env'])
                kwargs['stdout'].write('fixture-secret')
                kwargs['stderr'].write('fixture-secret-error')
                return subprocess.CompletedProcess(args, 1)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(bootstrap.subprocess, 'run', side_effect=execute):
                with self.assertRaises(bootstrap.SetupError) as caught:
                    cli.run(['apply', 'service-account'], 'output.yaml')
            self.assertNotIn('fixture-secret', str(caught.exception) + output.getvalue())

    def test_missing_scopes_accepts_the_broad_card_scope(self):
        def token(scope):
            payload = base64.urlsafe_b64encode(json.dumps({'scope': scope}).encode()).decode().rstrip('=')
            return 'e30.' + payload + '.sig'
        others = ' '.join(s for s in bootstrap.SCOPES if not s.startswith('cards:'))
        self.assertEqual(bootstrap.missing_scopes(token(others + ' cards:write cards:read')), [])
        self.assertEqual(bootstrap.missing_scopes(token(others + ' cards:read')), ['cards:create', 'cards:update'])
        self.assertEqual(bootstrap.missing_scopes('not-a-token'), [])

    def test_verify_uses_only_sandbox_read_endpoints(self):
        # Use the actual verifier, independent of the onboarding tests' mock.
        requests = []
        def response(req, **kwargs):
            requests.append(req)
            value = io.BytesIO(b'{"access_token":"fixture-access-token"}')
            value.status = 200
            return value
        with patch.object(bootstrap, 'urlopen', side_effect=response):
            bootstrap.verify({'VGS_CLIENT_ID': 'fixture', 'VGS_CLIENT_SECRET': 'fixture', 'VGS_TENANT': 'tntSandbox'})
        self.assertEqual([r.get_method() for r in requests], ['POST', 'GET', 'GET'])
        self.assertTrue(all(r.full_url.startswith(bootstrap.API) for r in requests[1:]))
        self.assertEqual(requests[1].get_header('Vgs-tenant'), 'tntSandbox')


if __name__ == '__main__': unittest.main()
