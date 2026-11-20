import hashlib
import unittest
from unittest.mock import patch

from check_publication import inspect_file


class PublicationTests(unittest.TestCase):
    def test_private_runtime_artifacts_cannot_be_packaged(self):
        for name in ['.private/config.json', '.state-test/sessions/RSABC.json',
                     'RSABC.request.json', 'capture.har', '.proxy-controls-egress.json',
                     'session-proxy-extension/background.js']:
            with self.subTest(name=name):
                self.assertTrue(inspect_file(name, b'const INITIAL_SESSION = {};'))

    def test_only_exact_reviewed_har_bytes_at_the_reviewed_path_are_allowed(self):
        name = 'examples/adapters/fixture/fixtures/checkout.synthetic.har'
        body = b'{"log":{"_synthetic":true,"entries":[]}}'
        with patch.dict('check_publication.PUBLIC_SYNTHETIC_HARS',
                        {name: hashlib.sha256(body).hexdigest()}, clear=True):
            self.assertFalse(inspect_file(name, body))
            self.assertIn('private runtime filename', inspect_file(name, body + b' '))
            self.assertIn('private runtime filename', inspect_file('capture.har', body))

    def test_reviewed_har_still_runs_content_checks(self):
        name = 'examples/adapters/fixture/fixtures/checkout.synthetic.har'
        body = b'/Users/' + b'fixture-user/private/file'
        with patch.dict('check_publication.PUBLIC_SYNTHETIC_HARS',
                        {name: hashlib.sha256(body).hexdigest()}, clear=True):
            self.assertIn('personal home directory', inspect_file(name, body))

    def test_private_content_is_rejected_without_printing_it(self):
        for body in [b'/Users/' + b'fixture-user/private/file',
                     b'-----BEGIN ' + b'PRIVATE KEY-----\n' + b'A' * 64,
                     b'ghp_' + b'a' * 40]:
            with self.subTest(body_length=len(body)):
                findings = inspect_file('README.md', body)
                self.assertTrue(findings)
                self.assertNotIn(body.decode(), str(findings))

    def test_public_templates_and_synthetic_fixtures_remain_valid(self):
        self.assertFalse(inspect_file('sandbox.env.example', b'VGS_CLIENT_SECRET=<YOUR_SECRET>'))
        self.assertFalse(inspect_file('test_fixture.py', b'password = "fixture-secret"'))
        self.assertFalse(inspect_file('README.md', b'/path/to/service-account.yaml'))

    def test_customer_docs_do_not_expose_internal_environment_setup(self):
        for body in [b'Use Dev', b'KIT_ENV=dev', b'?allow_dev_env=true',
                     b'https://sandbox.vgsapi.io', b'https://js.verygoodvault.io']:
            with self.subTest(body=body):
                self.assertTrue(inspect_file('guide.md', body))

    def test_customer_terms_and_internal_source_gate_remain_valid(self):
        self.assertFalse(inspect_file('README.md', b'Agent Web Gateway dev kit; Sandbox and Live. curl -o /dev/null'))
        self.assertFalse(inspect_file('popup.js', b'allow_dev_env=true'))


if __name__ == '__main__':
    unittest.main()
