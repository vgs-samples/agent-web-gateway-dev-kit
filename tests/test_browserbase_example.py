"""The Browserbase example builds its request from a reveal session without touching a network."""
import importlib.util
from pathlib import Path
import sys
import unittest

KIT = Path(__file__).resolve().parents[1]
SESSION = {
    'allowed_hosts': ['vendor.example'],
    'proxy': {'url': 'https://US%40fixture:fixture%2Fsecret@tntfixture.sandbox.verygoodproxy.com:3443',
              'ca_bundle': '-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n'},
    'cards': [{'label': 'main', 'number': {'alias': 'tok_fixture_pan', 'value': '4111110000001111'},
               'cvc': {'alias': 'tok_fixture_cvc', 'value': '987'}}],
}


class PaymentFlowTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('payment_flow', KIT / 'examples/browserbase/payment_flow.py')
        self.example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.example)

    def test_loading_the_example_needs_no_browser_package(self):
        self.assertNotIn('playwright', sys.modules)

    def test_the_browser_goes_through_the_session_and_trusts_its_certificate_authority(self):
        body = self.example.browser_request(SESSION, 'cert-fixture', 'project-fixture')
        self.assertEqual(body['proxies'], [{'type': 'external', 'server': 'https://tntfixture.sandbox.verygoodproxy.com:3443',
                                            'username': 'US@fixture', 'password': 'fixture/secret'}])
        self.assertEqual(body['proxySettings'], {'caCertificates': ['cert-fixture']})
        self.assertEqual(body['projectId'], 'project-fixture')
        self.assertNotIn('ignoreCertificateErrors', str(body))
        self.assertNotIn('projectId', self.example.browser_request(SESSION, 'cert-fixture'))

    def test_only_stand_ins_are_typed(self):
        self.assertEqual(self.example.stand_ins(SESSION), {'number': '4111110000001111', 'cvc': '987'})
        without_cvc = {**SESSION, 'cards': [{'number': SESSION['cards'][0]['number']}]}
        self.assertEqual(self.example.stand_ins(without_cvc), {'number': '4111110000001111'})
        self.assertNotIn('tok_fixture', str(self.example.stand_ins(SESSION)))


if __name__ == '__main__': unittest.main()
