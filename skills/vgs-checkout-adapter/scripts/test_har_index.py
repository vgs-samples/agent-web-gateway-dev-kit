"""Offline tests of body availability, decoding and private extraction."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('har-index.py')
spec = importlib.util.spec_from_file_location('har_index', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HarTests(unittest.TestCase):
    def test_body_availability_and_decoding(self):
        for value, state, data in [
            ({}, 'missing', None), ({'text': ''}, 'empty', b''),
            ({'text': 'aGVsbG8=', 'encoding': 'base64'}, 'present', b'hello'),
            ({'text': '!!!', 'encoding': 'base64'}, 'invalid-base64', None),
            ({'params': [{'name': 'x', 'value': 'y'}]}, 'params-only', None),
            ({'text': 'x', 'encoding': 'gzip'}, 'unsupported-encoding', None),
        ]:
            with self.subTest(state=state):
                info, actual = module.body_info(value)
                self.assertEqual(info['availability'], state)
                self.assertEqual(actual, data)

    def test_index_omits_secrets_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = json.dumps({'log': {'entries': [{
                'request': {'method': 'POST', 'url': 'https://user:pass@merchant.invalid/pay?secret=QUERY_SECRET',
                            'headers': [{'name': 'Authorization', 'value': 'HEADER_SECRET'}],
                            'postData': {'mimeType': 'application/json', 'text': 'BODY_SECRET'}},
                'response': {'status': 200, 'content': {'mimeType': 'text/plain'}}
            }]}}).encode()
            original = root / 'capture.har'
            original.write_bytes(raw)
            output = root / 'index.json'
            extracted = root / 'entry'
            run = subprocess.run([sys.executable, str(SCRIPT), str(original), '--output', str(output),
                                  '--entry', '0', '--extract-dir', str(extracted)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            text = output.read_text()
            for secret in ('QUERY_SECRET', 'HEADER_SECRET', 'BODY_SECRET', 'user:pass'):
                self.assertNotIn(secret, text)
            self.assertEqual(original.read_bytes(), raw)
            self.assertEqual((extracted / 'request.body').read_bytes(), b'BODY_SECRET')
            self.assertFalse((extracted / 'response.body').exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            # Exclusive output refuses to replace an original capture.
            run = subprocess.run([sys.executable, str(SCRIPT), str(original), '--output', str(original)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(original.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
