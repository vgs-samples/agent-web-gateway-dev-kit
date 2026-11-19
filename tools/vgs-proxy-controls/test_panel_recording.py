"""Recording lifecycle checks with synthetic traffic; no merchant or account access."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid

from panel_recording import TestRecording, RecordingError, test_address


class FakeCapture:
    def __init__(self, endpoint, directory, **kwargs):
        self.recording = None
        self.pages = {}
        self.selected = None
        self.order = []
        self.directory = Path(directory)
        self.browser = SimpleNamespace(contexts=[SimpleNamespace(new_page=self.new_page)], is_connected=lambda: True)

    async def connect(self): pass
    async def new_page(self):
        self.page_object = SimpleNamespace(url='about:blank', goto=self.navigate)
        return self.page_object
    def page(self, **kwargs): return self.page_object
    async def start(self):
        self.order.append('capture')
        self.recording = {'har': {'log': {'entries': [], '_capture': {'omittedRequests':0, 'excludedRequests':0, 'bodyErrors':0}}}}
        return {'captureId':'CAP' + 'a' * 32}
    async def navigate(self, url, **kwargs):
        self.order.append('navigate')
        if url.endswith('/failure'): raise OSError('PRIVATE URL AND SECRET')
        self.page_object.url = url
    async def stop(self, reason):
        self.recording = None
        return {'captureId':'CAP' + 'a'*32, 'path':str(self.directory/'fixture.har'), 'entries':4,
                'incompleteEntries':0, 'omittedRequests':0, 'excludedRequests':2, 'bodyErrors':0}
    async def close(self): pass


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rec = TestRecording('http://127.0.0.1:9222', self.temp.name, browser_factory=FakeCapture)
    def tearDown(self):
        self.rec.close()
        self.temp.cleanup()
    def options(self, url='https://merchant.invalid/start'):
        return {'requestId':str(uuid.uuid4()), 'url':url, 'sessionId':'RSFIXTURE', 'environment':'dev'}
    def wait(self, state):
        for _ in range(100):
            value = self.rec.status()
            if value['state'] == state: return value
            time.sleep(.01)
        self.fail('Expected state '+state)
    def test_recording_precedes_navigation_and_duplicate_start_never_navigates_twice(self):
        options = self.options()
        self.rec.start(options)
        self.wait('recording')
        self.rec.start(options)
        with self.assertRaises(RecordingError): self.rec.start(self.options())
        self.assertEqual(self.rec.browser.order, ['capture','navigate'])
        self.rec.stop()
        self.assertEqual(self.wait('saved')['entries'], 4)
        self.assertFalse(self.rec.status()['recording'])
    def test_failed_navigation_keeps_recording_without_private_error(self):
        self.rec.start(self.options('https://merchant.invalid/failure'))
        result = self.wait('recording')
        self.assertIn('still active', result['error'])
        self.assertNotIn('SECRET', json.dumps(result))
        self.rec.stop(); self.wait('saved')
    def test_capture_failure_does_not_navigate(self):
        class Broken(FakeCapture):
            async def start(self): raise OSError('SECRET')
        self.rec.browser_factory = Broken
        self.rec.start(self.options())
        result = self.wait('failed')
        self.assertEqual(self.rec.browser.order, [])
        self.assertNotIn('SECRET', json.dumps(result))
    def test_closing_selected_tab_automatically_saves(self):
        self.rec.start(self.options()); self.wait('recording')
        self.rec.browser.recording['har']['log']['_capture']['tabClosed'] = True
        for _ in range(150):
            if self.rec.status()['state'] == 'saved': break
            time.sleep(.01)
        self.assertEqual(self.rec.status()['stoppedReason'], 'tab-closed')
    def test_rejects_internal_and_tokenization_targets(self):
        for value in ('file:///private/card', 'https://user:password@merchant.invalid/',
                      'http://127.0.0.1:9222', 'https://sandbox.vgsapi.io/cards',
                      'https://tenant.sandbox.verygoodproxy.io/cards', 'https://tenant.verygoodproxy.com/aliases',
                      'https://js.verygoodvault.com/', 'https://vault.sandbox.vault-api.verygoodvault.com/cards'):
            with self.assertRaises(RecordingError): self.rec.start(self.options(value))
        self.assertEqual(self.rec.status()['state'], 'idle')

    def test_missing_profile_connection_is_explicit_and_does_not_open_a_tab(self):
        self.rec.endpoint = None
        self.rec.profile = Path(self.temp.name)
        self.assertIn('Relaunch', self.rec.status()['setupRequired'])
        self.rec.start(self.options())
        self.assertIn('Relaunch', self.wait('failed')['error'])
        self.assertIsNone(self.rec.browser)

    def test_saved_capture_runs_repair_and_keeps_har_when_repair_fails(self):
        calls = []
        def repair(cid):
            calls.append(cid)
            raise RuntimeError('SECRET')
        self.rec.repair = repair
        self.rec.start(self.options()); self.wait('recording')
        self.rec.stop(); self.wait('saved')
        for _ in range(100):
            if self.rec.status().get('repair', {}).get('status') == 'needs-review': break
            time.sleep(.01)
        state = self.rec.status()
        self.assertEqual(calls, [state['captureId']])
        self.assertEqual(state['state'], 'saved')
        self.assertEqual(state['repair']['status'], 'needs-review')
        self.assertNotIn('SECRET', json.dumps(state))


if __name__ == '__main__': unittest.main()
