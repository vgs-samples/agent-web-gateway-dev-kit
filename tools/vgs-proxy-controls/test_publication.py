import unittest

from check_publication import inspect_file


class PublicationTests(unittest.TestCase):
    def test_private_runtime_artifacts_cannot_be_packaged(self):
        for name in ['.private/config.json', '.state-test/sessions/RSABC.json',
                     'RSABC.request.json', 'capture.har', '.proxy-controls-egress.json',
                     'session-proxy-extension/background.js']:
            with self.subTest(name=name):
                self.assertTrue(inspect_file(name, b'const INITIAL_SESSION = {};'))

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


if __name__ == '__main__':
    unittest.main()
