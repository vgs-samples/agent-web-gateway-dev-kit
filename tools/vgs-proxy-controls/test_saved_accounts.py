"""Credential discovery uses synthetic private files and never contacts VGS."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from account_files import AccountFileError
from environments import EnvironmentClient
from saved_accounts import account_directory, default_account, main, saved_accounts
from session_catalog import Catalog, CatalogServer


class SavedAccountsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        override = patch.dict(os.environ, {'AWG_HOME': str(self.root)})
        override.start()
        self.addCleanup(override.stop)

    def account(self, environment, name, content=None):
        path = self.root / environment / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content or 'VGS_TENANT=tntFixture\nVGS_CLIENT_ID=fixture-id\nVGS_CLIENT_SECRET=fixture-secret-never-return\n')
        path.chmod(0o600)
        return path

    def test_default_and_override_have_separate_environment_directories(self):
        with patch.dict(os.environ, {'AWG_HOME': ''}), patch.object(Path, 'home', return_value=self.root):
            for environment in ('dev', 'sandbox', 'live'):
                self.assertEqual(account_directory(environment), self.root / '.vgs' / 'awg' / environment)
        self.assertEqual(account_directory('dev'), self.root / 'dev')
        with self.assertRaises(AccountFileError):
            account_directory('../sandbox')

    def test_lists_all_supported_exports_in_only_the_selected_environment(self):
        env = self.account('dev', 'dev.env')
        dashboard = self.account('dev', 'Dashboard export ü.txt', 'clientId=fixture-id\nclientSecret=fixture-secret-never-return\n')
        yaml = self.account('dev', 'second.yaml', 'kind: ServiceAccount\ndata:\n  clientId: fixture-id\n  clientSecret: fixture-secret-never-return\n  vaults: [tntFixture]\n')
        js = self.account('dev', 'third.json', json.dumps({'clientId': 'fixture-id', 'clientSecret': 'fixture-secret-never-return'}))
        self.account('sandbox', 'sandbox.env')
        self.account('live', 'live.env')
        listing = saved_accounts('dev')
        self.assertEqual([row['path'] for row in listing['credentialFiles']], sorted(map(str, (env, dashboard, yaml, js))))
        self.assertNotIn('fixture-secret', json.dumps(listing))
        self.assertNotIn('fixture-id', json.dumps(listing))

    def test_ignores_journals_non_accounts_wrong_environments_and_symlinks(self):
        self.account('dev', 'setup/account.env')
        self.account('dev', 'session.json', '{"data":{"id":"RSFixture"}}')
        self.account('dev', 'config.yaml', 'kind: ServiceAccount\ndata:\n  name: definition-only\n')
        self.account('dev', 'wrong.env', 'VGS_CLIENT_ID=fixture-id\nVGS_CLIENT_SECRET=fixture-secret\nVGS_ENVIRONMENT=live\n')
        self.account('dev', 'large.env', 'x' * 65537)
        target = self.account('live', 'live.env')
        (self.root / 'dev' / 'link.env').symlink_to(target)
        os.mkfifo(self.root / 'dev' / 'pipe.env')
        self.assertEqual(saved_accounts('dev')['credentialFiles'], [])

    def test_empty_and_unreadable_folders_are_safe(self):
        self.assertEqual(saved_accounts('sandbox')['credentialFiles'], [])
        with patch.object(Path, 'iterdir', side_effect=PermissionError('fixture-private-detail')):
            listing = saved_accounts('dev')
        self.assertIn('credentialsError', listing)
        self.assertNotIn('fixture-private-detail', json.dumps(listing))

    def test_default_uses_canonical_or_only_account_and_rejects_ambiguity(self):
        first = self.account('sandbox', 'first.json', '{"clientId":"fixture-id","clientSecret":"fixture-secret"}')
        self.assertEqual(default_account('sandbox'), first)
        self.account('sandbox', 'second.env')
        with self.assertRaises(AccountFileError):
            default_account('sandbox')
        canonical = self.account('sandbox', 'sandbox.env')
        self.assertEqual(default_account('sandbox'), canonical)

    def test_cli_lists_every_environment_without_secret_values_or_network(self):
        for environment in ('dev', 'sandbox', 'live'):
            self.account(environment, environment + '.env')
        output = io.StringIO()
        with patch('sys.argv', ['saved_accounts.py']), contextlib.redirect_stdout(output), patch.object(EnvironmentClient, 'token', side_effect=AssertionError('network forbidden')):
            main()
        for environment in ('dev', 'sandbox', 'live'):
            self.assertIn(environment + '.env', output.getvalue())
        self.assertNotIn('fixture-secret', output.getvalue())

    def test_listing_endpoint_requires_helper_auth_and_works_before_account_connection(self):
        initial = Catalog(None, EnvironmentClient(self.account('dev', 'dev.env'), 'dev'), self.root / 'sessions', ca_bundle='fixture-ca', use_settings=False)
        server = CatalogServer(None, catalog=initial, profiles={})
        self.addCleanup(server.close)
        self.account('live', 'live.env')
        url = server.config['url'] + '/environments/live/credentials/files'
        headers = {'Authorization': 'Bearer ' + server.config['token']}
        with patch.object(EnvironmentClient, 'token', side_effect=AssertionError('network forbidden')):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url))
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            with urlopen(Request(url, headers=headers)) as response:
                listing = json.load(response)
        self.assertEqual([row['name'] for row in listing['credentialFiles']], ['live.env'])
        self.assertNotIn('fixture-secret', json.dumps(listing))
