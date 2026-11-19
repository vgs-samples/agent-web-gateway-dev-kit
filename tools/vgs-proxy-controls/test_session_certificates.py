"""Saved public certificates are isolated by environment, tenant and session."""
import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from environments import domains
from session_certificates import CertificateError, session_certificate, SessionDetailsError, session_details

PEM = '-----BEGIN CERTIFICATE-----\n' + base64.b64encode(b'synthetic-certificate').decode() + '\n-----END CERTIFICATE-----\n'


class CertificateTests(unittest.TestCase):
    def test_exports_each_environment_without_credentials_or_pac_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            for environment in ('dev', 'sandbox', 'live'):
                catalog = SimpleNamespace(environment=environment, tenant='fixtureTenant', saved=lambda sid:path)
                proxy = {'url':domains(environment, catalog.tenant)['proxy'].replace('https://','https://private:secret@'),
                         'ca_bundle':PEM, 'pac_url':'private-signature'}
                path.write_text(json.dumps({'data':{'id':'RSFIXTURE','attributes':{'proxy':proxy}}}))
                result = session_certificate(catalog, 'RSFIXTURE')
                self.assertEqual(result['caBundle'], PEM)
                self.assertEqual(result['filename'], f'vgs-{environment}-RSFIXTURE-ca.pem')
                self.assertNotIn('secret', json.dumps(result))
                self.assertNotIn('signature', json.dumps(result))
                self.assertEqual(len(result['sha256Fingerprints'][0]), 95)
                for bad in ('RSOTHER', '../RSFIXTURE'):
                    with self.assertRaises(CertificateError): session_certificate(catalog, bad)
                catalog.environment = 'live' if environment != 'live' else 'sandbox'
                with self.assertRaises(CertificateError): session_certificate(catalog, 'RSFIXTURE')
                catalog.environment = environment; catalog.tenant = 'otherTenant'
                with self.assertRaises(CertificateError): session_certificate(catalog, 'RSFIXTURE')

    def test_rejects_private_key_or_missing_certificate_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            catalog = SimpleNamespace(environment='sandbox', tenant='fixtureTenant', saved=lambda sid:path)
            for pem in ('secret', PEM + '-----BEGIN PRIVATE KEY-----\nsecret', '', None):
                path.write_text(json.dumps({'data':{'id':'RSFIXTURE','attributes':{'proxy':{
                    'url':domains('sandbox',catalog.tenant)['proxy'], 'ca_bundle':pem}}}}))
                with self.assertRaises(CertificateError) as error: session_certificate(catalog,'RSFIXTURE')
                self.assertNotIn('secret', str(error.exception))


class SessionDetailsTests(unittest.TestCase):
    def test_details_keep_standins_and_current_status_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            current = {'data':{'id':'RSFIXTURE','attributes':{'state':'revoked','expires_at':'2099-02-01T00:00:00Z'}}}
            catalog = SimpleNamespace(environment='live',tenant='fixtureTenant',saved=lambda sid:path,
                client=SimpleNamespace(api=lambda method,url: current))
            attrs = {'proxy':{'url':domains('live',catalog.tenant)['proxy'].replace(':8443', ':3443').replace('https://','https://PRIVATE_USER:PRIVATE_PASSWORD@'),
                'pac_url':'https://private/?signature=PRIVATE_SIGNATURE','ca_bundle':'PRIVATE_CERT'},
                'tokens':[{'format':'card_number','value':'fixture-standin','alias':'PRIVATE_ALIAS'}],
                'state':'active','expires_at':'2099-01-01T00:00:00Z','adapter':'ADfixture',
                'egress_proxy_settings':{'type':'custom','scheme':'http','hostname':'fixture-host','port':8080,'username':'PRIVATE_EGRESS','password':'PRIVATE_PASSWORD'}}
            path.write_text(json.dumps({'data':{'id':'RSFIXTURE','attributes':attrs}}))
            result = session_details(catalog,'RSFIXTURE')
            self.assertEqual(result['tokens'],[{'format':'card_number','value':'fixture-standin'}])
            self.assertEqual(result['settings']['state'],'revoked')
            self.assertEqual(result['settings']['expires_at'],'2099-02-01T00:00:00Z')
            self.assertEqual(result['settings']['adapter'],'ADfixture')
            self.assertNotIn('PRIVATE_',json.dumps(result))
            class ExpiredError(Exception): status = 404
            def unavailable(*args): raise ExpiredError()
            catalog.client.api = unavailable
            attrs['expires_at'] = '2000-01-01T00:00:00Z'
            path.write_text(json.dumps({'data':{'id':'RSFIXTURE','attributes':attrs}}))
            self.assertEqual(session_details(catalog,'RSFIXTURE')['settings']['state'],'expired')
            ExpiredError.status = 403
            with self.assertRaises(SessionDetailsError):session_details(catalog,'RSFIXTURE')
            catalog.client.api = lambda method,url:current
            for sid in ('../RSFIXTURE','RSOTHER'):
                with self.assertRaises(SessionDetailsError):session_details(catalog,sid)
            catalog.environment='sandbox'
            with self.assertRaises(SessionDetailsError):session_details(catalog,'RSFIXTURE')
            catalog.environment='live'; catalog.tenant='otherTenant'
            with self.assertRaises(SessionDetailsError):session_details(catalog,'RSFIXTURE')


class LocalTrustTests(unittest.TestCase):
    def test_native_check_uses_existing_ssl_trust_without_installing_anchor(self):
        import session_certificates as module
        from unittest.mock import patch
        with patch.object(module.sys, 'platform', 'darwin'), patch.object(module.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertTrue(module.ca_trusted_locally(PEM))
            args, options = run.call_args
            self.assertEqual(args[0][:3], ['/usr/bin/security', 'verify-cert', '-c'])
            self.assertIn('ssl', args[0]); self.assertIn('-L', args[0]); self.assertIn('-l', args[0])
            self.assertNotIn('-r', args[0]); self.assertNotIn('add-trusted-cert', args[0])
            self.assertFalse(Path(args[0][3]).exists())
            run.return_value.returncode = 1
            self.assertFalse(module.ca_trusted_locally(PEM))
            run.side_effect = module.subprocess.TimeoutExpired('security', 5)
            self.assertFalse(module.ca_trusted_locally(PEM))

    def test_bad_input_and_unsupported_platform_never_probe(self):
        import session_certificates as module
        from unittest.mock import patch
        with patch.object(module.subprocess, 'run') as run:
            with patch.object(module.sys, 'platform', 'darwin'):
                for value in (None, '', 'not a certificate', PEM + 'PRIVATE KEY', 'x' * 131073):
                    self.assertFalse(module.ca_trusted_locally(value))
            with patch.object(module.sys, 'platform', 'linux'):
                self.assertFalse(module.ca_trusted_locally(PEM))
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
