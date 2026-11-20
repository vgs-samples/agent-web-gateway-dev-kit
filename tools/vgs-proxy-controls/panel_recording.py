"""Panel-owned recording lifecycle; does not require an MCP client or account access."""
import asyncio
from copy import deepcopy
from pathlib import Path
import threading
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

from capture_preferences import har_recording_filter
from mcp_capture import BrowserCapture


class RecordingError(ValueError):
    pass


def test_address(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise RecordingError('Enter an HTTP or HTTPS test address.')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or any(c.isspace() for c in value) or not har_recording_filter().match(value)):
            raise ValueError()
        parsed.port
    except ValueError:
        raise RecordingError('Enter a merchant HTTP or HTTPS address without credentials. Local helper and VGS tokenization pages are excluded.') from None
    return value


def display_address(value):
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


class TestRecording:
    """One recorder per helper, shared by every panel tab. HTTP methods return promptly."""
    __test__ = False

    def __init__(self, endpoint, directory, *, browser_factory=BrowserCapture, url_filter=None, profile=None, repair=None):
        self.endpoint, self.directory = endpoint, Path(directory)
        self.profile = Path(profile) if profile else None
        self.repair = repair
        self.repair_tasks = set()
        self.browser_factory = browser_factory
        self.url_filter = url_filter or (lambda url: bool(har_recording_filter().match(url)))
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name='awg-test-recording')
        self.lock = threading.Lock()
        self.stop_lock = asyncio.Lock()
        self.snapshot = {'state': 'idle', 'recording': False, 'entries': 0}
        self.browser = None
        self.operation = None
        self.monitor = None
        self.thread.start()

    def status(self):
        with self.lock:
            value = deepcopy(self.snapshot)
        if not self.endpoint and self.profile and not (self.profile / 'DevToolsActivePort').is_file():
            value['setupRequired'] = 'Relaunch this test browser with recording support. Its current launch has no recording connection.'
        return value

    def update(self, **values):
        with self.lock:
            self.snapshot.update(values)

    async def recorder(self):
        if self.browser is None:
            endpoint = self.endpoint
            if not endpoint and self.profile:
                try:
                    port = int((self.profile / 'DevToolsActivePort').read_text().splitlines()[0])
                    if not 1 <= port <= 65535: raise ValueError()
                except (OSError, ValueError, IndexError):
                    raise RecordingError('Relaunch this test browser with recording support. Its profile has no local debugging connection.') from None
                endpoint = f'http://127.0.0.1:{port}'
            self.browser = self.browser_factory(endpoint or 'http://127.0.0.1:9222', self.directory, url_filter=self.url_filter)
        return self.browser

    def tabs(self):
        async def read():
            browser = await self.recorder()
            return [{'tabId': row['tabId'], 'title': row['title'], 'url': display_address(row['url'])}
                    for row in await browser.tabs() if self.url_filter(row['url'])]
        pending = asyncio.run_coroutine_threadsafe(read(), self.loop)
        try:
            return pending.result(timeout=15)
        except Exception:
            pending.cancel()
            raise RecordingError('Cannot connect to the testing browser. Start it with local debugging enabled at the helper’s configured recording address.') from None

    def start(self, options):
        if not isinstance(options, dict) or set(options) - {'tabId', 'url', 'requestId', 'sessionId', 'environment'}:
            raise RecordingError('Choose a test tab and address.')
        rid, tab_id = options.get('requestId'), options.get('tabId')
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9-]{36}', rid):
            raise RecordingError('Refresh the panel before starting a test.')
        address = test_address(options['url']) if options.get('url') else ''
        if tab_id is not None and (not isinstance(tab_id, str) or not re.fullmatch(r'TAB[a-f0-9]{32}', tab_id)):
            raise RecordingError('Refresh the testing tabs.')
        if not tab_id and not address:
            raise RecordingError('Enter an address for the new test tab.')
        with self.lock:
            if self.snapshot.get('requestId') == rid:
                return deepcopy(self.snapshot)
            if self.snapshot['state'] in ('starting', 'recording', 'stopping'):
                raise RecordingError('Stop and save the current test first.')
            self.snapshot = {'state': 'starting', 'recording': False, 'entries': 0, 'requestId': rid,
                             'url': display_address(address) if address else '', 'error': None}
            result = deepcopy(self.snapshot)
            self.operation = asyncio.run_coroutine_threadsafe(self._start(tab_id, address, options), self.loop)
        return result

    async def _start(self, tab_id, address, options):
        try:
            browser = await self.recorder()
            await browser.connect()
            if tab_id:
                await browser.select(tab_id)
                if not self.url_filter(browser.page().url):
                    raise RecordingError('Choose a merchant tab. Tokenization and local helper traffic are excluded.')
            else:
                if len(browser.browser.contexts) != 1:
                    raise RecordingError('Choose an existing tab when multiple browser contexts are open.')
                page = await browser.browser.contexts[0].new_page()
                tab_id = 'TAB' + uuid.uuid4().hex
                browser.pages[tab_id], browser.selected = page, tab_id
            # Install request/frame listeners and persist the first checkpoint BEFORE navigation.
            capture = await browser.start()
            capture_meta = browser.recording['har']['log']['_capture']
            capture_meta['testUrl'] = address or browser.page(allow_blank=True).url
            capture_meta['testContext'] = {key: options.get(key) for key in ('sessionId', 'environment')}
            self.update(state='recording', recording=True, captureId=capture['captureId'],
                        url=display_address(address or browser.page(allow_blank=True).url), error=None)
            self.monitor = asyncio.create_task(self._monitor(browser.recording))
            if address:
                try:
                    await browser.page(allow_blank=True).goto(address, wait_until='domcontentloaded', timeout=30000)
                except Exception:
                    self.update(error='The page did not finish loading. Recording is still active; the failed navigation is included.')
        except Exception as error:
            if self.browser and self.browser.recording:
                await self._stop('start-failed')
            self.update(state='failed', recording=False, error=str(error) if isinstance(error, RecordingError) else
                        'Recording could not start. Check the local debugging address and install the helper’s recording dependency. No test navigation was started.')

    async def _monitor(self, record):
        while self.browser and self.browser.recording is record:
            await asyncio.sleep(1)
            if self.browser.recording is not record:
                break
            meta = record['har']['log']['_capture']
            if meta.get('tabClosed') or not self.browser.browser.is_connected():
                await self._stop('tab-closed' if meta.get('tabClosed') else 'browser-disconnected')
                break
            self.update(entries=len(record['har']['log']['entries']), omittedRequests=meta['omittedRequests'],
                        excludedRequests=meta['excludedRequests'], bodyErrors=meta['bodyErrors'],
                        checkpointError=bool(meta.get('checkpointError')))

    def stop(self):
        with self.lock:
            state = self.snapshot['state']
            if state == 'starting':
                raise RecordingError('Wait for recording to start before stopping it.')
            if state != 'recording':
                return deepcopy(self.snapshot)
            self.snapshot['state'] = 'stopping'
            if self.operation and not self.operation.done():
                self.operation.cancel()
            self.operation = asyncio.run_coroutine_threadsafe(self._stop('stopped'), self.loop)
            return deepcopy(self.snapshot)

    async def _stop(self, reason):
        async with self.stop_lock:
            await self._save(reason)

    async def _save(self, reason):
        try:
            if self.browser and self.browser.recording:
                result = await self.browser.stop(reason)
                self.update(state='saved', recording=False, **{key: result[key] for key in
                    ('captureId', 'path', 'entries', 'incompleteEntries', 'omittedRequests', 'bodyErrors', 'excludedRequests')},
                    stoppedReason=reason)
                if self.repair and reason != 'helper-stopped':
                    self.update(repair={'status': 'checking', 'message': 'Checking the captured failure against DEV configuration…'})
                    task = asyncio.create_task(self._repair(result['captureId']))
                    self.repair_tasks.add(task)
                    task.add_done_callback(self.repair_tasks.discard)
        except Exception:
            self.update(state='failed', recording=False,
                        error='Final HAR save failed. The last local checkpoint may be incomplete; check the capture folder.')

    async def _repair(self, capture_id):
        try:
            result = await asyncio.to_thread(self.repair, capture_id)
        except Exception:
            result = {'status': 'needs-review', 'message': 'HAR saved. Repair could not complete; inspect DEV connectivity and the private repair journal.'}
        with self.lock:
            if self.snapshot.get('captureId') == capture_id:
                self.snapshot['repair'] = result

    def close(self):
        async def finish():
            if self.monitor:
                self.monitor.cancel()
                await asyncio.gather(self.monitor, return_exceptions=True)
            if self.operation and not self.operation.done():
                self.operation.cancel()
            await self._stop('helper-stopped')
            if self.repair_tasks:
                await asyncio.gather(*self.repair_tasks, return_exceptions=True)
            if self.browser:
                await self.browser.close()
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending: task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            asyncio.run_coroutine_threadsafe(finish(), self.loop).result(timeout=20)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            if not self.thread.is_alive(): self.loop.close()
