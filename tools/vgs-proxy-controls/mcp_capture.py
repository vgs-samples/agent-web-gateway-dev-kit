"""Selected-tab HAR recorder. Captured headers and bodies are intentionally unredacted."""
import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid
from urllib.parse import parse_qsl, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from awg_dev_api import NoRedirect
from mcp_gateway import loopback_url
from session_operations import private_json


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded_body(data):
    try:
        return {'text': data.decode('utf-8')}
    except UnicodeDecodeError:
        return {'text': base64.b64encode(data).decode('ascii'), 'encoding': 'base64'}


def body_allowed(data, meta):
    if len(data) > meta['maxBodyBytes'] or meta['capturedBodyBytes'] + len(data) > meta['maxTotalBodyBytes']:
        meta['bodyErrors'] += 1
        return False
    meta['capturedBodyBytes'] += len(data)
    return True


def cookies(headers, response=False):
    # Preserve the exact Cookie/Set-Cookie headers; these parsed rows are convenience only.
    from http.cookies import SimpleCookie
    rows = []
    for h in headers:
        if h['name'].lower() != ('set-cookie' if response else 'cookie'): continue
        parsed = SimpleCookie()
        try: parsed.load(h['value'])
        except Exception: continue
        for name, value in parsed.items():
            row = {'name': name, 'value': value.value}
            if response:
                row.update(httpOnly=bool(value['httponly']), secure=bool(value['secure']))
                for key in ('path', 'domain'):
                    if value[key]: row[key] = value[key]
                if value['expires']:
                    from email.utils import parsedate_to_datetime
                    try: row['expires'] = parsedate_to_datetime(value['expires']).isoformat()
                    except (ValueError, TypeError, OverflowError): pass
            rows.append(row)
    return rows


class CaptureStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def path(self, capture_id):
        if not re.fullmatch(r'CAP[a-f0-9]{32}', capture_id):
            raise ValueError('Invalid capture ID.')
        path = self.directory / (capture_id + '.har')
        if path.is_symlink(): raise ValueError('Capture files must not be symlinks.')
        return path

    def write(self, capture_id, har):
        private_json(self.path(capture_id), har)

    def read(self, capture_id):
        return json.loads(self.path(capture_id).read_text())

    def listing(self):
        rows = []
        for path in sorted(self.directory.glob('CAP*.har'), reverse=True):
            if not re.fullmatch(r'CAP[a-f0-9]{32}', path.stem) or path.is_symlink(): continue
            har = self.read(path.stem)
            rows.append({'captureId': path.stem, **har['log']['_capture'], 'entries': len(har['log']['entries'])})
        return sorted(rows, key=lambda row: row.get('startedAt', ''), reverse=True)


class BrowserCapture:
    def __init__(self, endpoint, directory):
        self.endpoint, self.store = loopback_url(endpoint), CaptureStore(directory)
        self.playwright = self.browser = self.selected = self.recording = None
        self.pages = {}
        self.lock = asyncio.Lock()

    async def connect(self):
        if self.browser and self.browser.is_connected(): return
        if self.recording:
            await self.stop('browser-disconnected')
        if self.playwright: await self.playwright.stop()
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        # CDP is local; a dedicated profile is required. No proxy mode is changed.
        def debugging_socket():
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(Request(self.endpoint + '/json/version'), timeout=10) as response:
                value = json.loads(response.read(65536))
            address = value['webSocketDebuggerUrl']
            parsed = urlsplit(address)
            if (parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1' or parsed.port != urlsplit(self.endpoint).port
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or not parsed.path.startswith('/devtools/browser/')):
                raise ValueError('The browser returned an unexpected debugging endpoint.')
            return address
        self.browser = await self.playwright.chromium.connect_over_cdp(await asyncio.to_thread(debugging_socket), timeout=10000)
        self.pages = {}
        self.selected = None

    async def tabs(self):
        await self.connect()
        rows = []
        live = [p for c in self.browser.contexts for p in c.pages if not p.is_closed() and urlsplit(p.url).scheme in ('http', 'https')]
        self.pages = {key: page for key, page in self.pages.items() if page in live}
        for page in live:
            key = next((key for key, known in self.pages.items() if known is page), None)
            if not key:
                key = 'TAB' + uuid.uuid4().hex
                self.pages[key] = page
            rows.append({'tabId': key, 'url': page.url, 'title': await page.title(), 'selected': key == self.selected})
        return rows

    async def select(self, tab_id):
        await self.tabs()
        if self.recording: raise ValueError('Stop the current capture before changing tabs.')
        if tab_id not in self.pages: raise ValueError('Tab is unavailable. List tabs again.')
        self.selected = tab_id
        return {'tabId': tab_id, 'url': self.pages[tab_id].url}

    def page(self):
        page = self.pages.get(self.selected)
        if not page or page.is_closed(): raise ValueError('Select an available HTTP or HTTPS tab first.')
        if urlsplit(page.url).scheme not in ('http', 'https'): raise ValueError('The selected tab is no longer an HTTP or HTTPS page.')
        return page

    async def start(self, max_entries=2000, max_body_bytes=20000000, max_total_body_bytes=100000000):
        await self.connect()
        if self.recording: raise ValueError('A capture is already running. Stop it first.')
        if (not 1 <= max_entries <= 10000 or not 1 <= max_body_bytes <= 100000000
                or not 1 <= max_total_body_bytes <= 500000000):
            raise ValueError('Capture limits are out of range.')
        page = self.page()
        capture_id = 'CAP' + uuid.uuid4().hex
        meta = {'tabId': self.selected, 'url': page.url, 'startedAt': now(), 'state': 'recording',
                'unredacted': True, 'maxEntries': max_entries, 'maxBodyBytes': max_body_bytes,
                'maxTotalBodyBytes': max_total_body_bytes, 'capturedBodyBytes': 0,
                'omittedRequests': 0, 'bodyErrors': 0}
        har = {'log': {'version': '1.2', 'creator': {'name': 'Agent Web Gateway Testing', 'version': '1.8.0'},
                       'pages': [], 'entries': [], '_capture': meta}}
        record = {'id': capture_id, 'har': har, 'requests': {}, 'tasks': set(), 'page': page, 'listeners': {}}
        self.recording = record

        def task(coro):
            pending = asyncio.create_task(coro)
            record['tasks'].add(pending)
            pending.add_done_callback(record['tasks'].discard)

        def request_started(request):
            if urlsplit(request.url).scheme not in ('http', 'https'): return
            if len(har['log']['entries']) >= max_entries:
                meta['omittedRequests'] += 1
                return
            entry = {'startedDateTime': now(), 'time': 0, 'request': {'method': request.method, 'url': request.url,
                'httpVersion': '', 'headers': [], 'queryString': [{'name': k, 'value': v} for k, v in parse_qsl(urlsplit(request.url).query, keep_blank_values=True)],
                'cookies': [], 'headersSize': -1, 'bodySize': -1},
                'response': {'status': 0, 'statusText': '', 'httpVersion': '', 'headers': [], 'cookies': [],
                    'content': {'size': 0, 'mimeType': ''}, 'redirectURL': '', 'headersSize': -1, 'bodySize': -1},
                'cache': {}, 'timings': {'send': 0, 'wait': 0, 'receive': 0},
                '_requestId': 'REQ' + uuid.uuid4().hex, '_resourceType': request.resource_type, '_state': 'pending'}
            har['log']['entries'].append(entry)
            record['requests'][request] = entry
            task(self.request_details(request, entry, meta))

        def request_finished(request):
            if request in record['requests']: task(self.finish(request, record['requests'][request], meta))

        def request_failed(request):
            if request in record['requests']:
                entry = record['requests'][request]
                entry.update(_state='failed', _error=request.failure or 'Request failed')
                task(self.finish(request, entry, meta, failed=True))

        def page_closed():
            meta['tabClosed'] = True

        record['listeners'] = {'request': request_started, 'requestfinished': request_finished,
                               'requestfailed': request_failed, 'close': page_closed}
        for event, listener in record['listeners'].items(): page.on(event, listener)
        # Save a checkpoint immediately. On an unclean shutdown it is explicitly incomplete.
        self.store.write(capture_id, har)
        async def checkpoint():
            while True:
                await asyncio.sleep(5)
                try:
                    meta['checkpointAt'] = now()
                    self.store.write(capture_id, har)
                except OSError:
                    meta['checkpointError'] = True
        record['checkpoint'] = asyncio.create_task(checkpoint())
        return {'captureId': capture_id, **meta}

    async def request_details(self, request, entry, meta):
        try:
            headers = await request.headers_array()
            entry['request'].update(headers=headers, cookies=cookies(headers))
            data = request.post_data_buffer
            if data is not None:
                entry['request']['bodySize'] = len(data)
                mime = next((h['value'] for h in headers if h['name'].lower() == 'content-type'), '')
                if not body_allowed(data, meta):
                    entry['request']['_bodyError'] = 'Body exceeds configured per-body or total capture limit'
                else:
                    body = encoded_body(data)
                    if 'encoding' in body: body['_encoding'] = body.pop('encoding')
                    entry['request']['postData'] = {'mimeType': mime, **body}
        except Exception:
            entry['request']['_captureError'] = 'Browser could not supply complete request headers or body'

    async def finish(self, request, entry, meta, failed=False):
        try:
            response = await request.response()
            if response:
                headers = await response.headers_array()
                target = entry['response']
                target.update(status=response.status, statusText=response.status_text, headers=headers,
                    cookies=cookies(headers, True), redirectURL=next((h['value'] for h in headers if h['name'].lower() == 'location'), ''))
                target['content']['mimeType'] = next((h['value'] for h in headers if h['name'].lower() == 'content-type'), '')
                try:
                    data = await response.body()
                    target['content']['size'] = len(data)
                    if body_allowed(data, meta):
                        target['content'].update(encoded_body(data))
                    else:
                        target['content']['_error'] = 'Body exceeds configured per-body or total capture limit'
                except Exception:
                    target['content']['_error'] = 'Body unavailable (redirect, closed tab, browser eviction, or configured size limit)'
                    meta['bodyErrors'] += 1
            timing = request.timing
            end = max(0, timing.get('responseEnd', 0))
            start = max(0, timing.get('requestStart', 0))
            received = max(start, timing.get('responseStart', start))
            entry.update(time=end, timings={'send': 0, 'wait': received - start, 'receive': max(0, end - received), 'blocked': start})
            entry['_state'] = 'failed' if failed else 'finished'
        except Exception:
            entry.update(_state='incomplete', _error='Browser disconnected or request details unavailable')

    async def stop(self, reason='stopped'):
        record = self.recording
        if not record: raise ValueError('No capture is running.')
        for event, listener in record['listeners'].items(): record['page'].remove_listener(event, listener)
        record['checkpoint'].cancel()
        await asyncio.gather(record['checkpoint'], return_exceptions=True)
        if record['tasks']:
            _, pending = await asyncio.wait(list(record['tasks']), timeout=10)
            for task in pending: task.cancel()
            if pending: await asyncio.gather(*pending, return_exceptions=True)
        for entry in record['har']['log']['entries']:
            if entry['_state'] == 'pending':
                entry.update(_state='incomplete', _error='Capture stopped before request completed')
        meta = record['har']['log']['_capture']
        meta.update(state=reason, stoppedAt=now())
        meta['incompleteEntries'] = sum(e['_state'] in ('pending', 'incomplete') for e in record['har']['log']['entries'])
        self.store.write(record['id'], record['har'])
        self.recording = None
        return {'captureId': record['id'], 'path': str(self.store.path(record['id'])),
                'entries': len(record['har']['log']['entries']), **meta}

    def status(self):
        if not self.recording: return {'recording': False, 'selectedTab': self.selected}
        return {'recording': True, 'captureId': self.recording['id'],
                'entries': len(self.recording['har']['log']['entries']), **self.recording['har']['log']['_capture']}

    async def close(self):
        if self.recording: await self.stop('mcp-disconnected')
        # Disconnect Playwright; never close the user's browser or its tabs.
        if self.playwright: await self.playwright.stop()
