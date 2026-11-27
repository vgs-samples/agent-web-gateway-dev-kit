#!/usr/bin/env python3
"""Index a private HAR without printing headers, query strings or body values.

Paths can still contain identifiers. This tool is not a sanitizer.
"""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def sha(data):
    return hashlib.sha256(data).hexdigest()


def body_info(body):
    if not isinstance(body, dict) or not isinstance(body.get('text'), str):
        state = 'params-only' if isinstance(body, dict) and body.get('params') else 'missing'
        return {'availability': state}, None
    encoding = body.get('encoding', 'text')
    try:
        if encoding == 'base64':
            data = base64.b64decode(''.join(body['text'].split()), validate=True)
        elif encoding in ('text', ''):
            data = body['text'].encode('utf-8')
        else:
            return {'availability': 'unsupported-encoding', 'encoding': encoding}, None
    except (ValueError, UnicodeError):
        return {'availability': 'invalid-base64'}, None
    info = {'availability': 'empty' if not data else 'present', 'encoding': encoding,
            'decodedBytes': len(data), 'sha256': sha(data)}
    return info, data


def index_har(raw):
    har = json.loads(raw)
    entries = har['log']['entries']
    result = {'harSha256': sha(raw), 'entryCount': len(entries),
              'warning': 'Local index, not sanitized output; paths may contain private identifiers.',
              'entries': []}
    for i, entry in enumerate(entries):
        req, res = entry.get('request', {}), entry.get('response', {})
        url = urlsplit(req.get('url', ''))
        post, content = req.get('postData', {}), res.get('content', {})
        request_info, _ = body_info(post)
        response_info, _ = body_info(content)
        result['entries'].append({
            'index': i, 'host': url.hostname, 'method': req.get('method'), 'path': url.path,
            'status': res.get('status'), 'requestMimeType': post.get('mimeType'),
            'responseMimeType': content.get('mimeType'),
            'requestBody': request_info, 'responseBody': response_info,
            'requestCaptureMetadataPresent': '_bodyCapture' in req})
    return result, entries


def request_envelope(data):
    if data.startswith(b'AWGCS1:'):
        if re.fullmatch(rb'AWGCS1:(?:[a-p]{2})+', data):
            return 'AWGCS1-relay-shaped'
        return 'AWGCS1-invalid-encoding'
    parts = data.split(b'.', 5)
    if len(parts) in (3, 5) and all(re.fullmatch(rb'[A-Za-z0-9_-]+', part) for part in parts):
        return 'compact-JWS-shaped' if len(parts) == 3 else 'compact-JWE-shaped'
    return 'other'


def cache_evidence(entry, response):
    if response.get('status') == 304:
        return 'revalidated-304'
    for record in (entry, response):
        if (record.get('_fromCache') in (True, 'disk', 'memory') or
                record.get('_fromDiskCache') is True or record.get('_fromMemoryCache') is True):
            return 'cache-flag'
    return 'none-recorded'


def header_values(headers, name):
    return [h['value'].strip().lower() for h in headers if h['name'].lower() == name]


def stage_evidence(stage, route, entry):
    req, res = entry['request'], entry.get('response', {})
    status = res.get('status')
    headers = res.get('headers', [])
    upstream_statuses = set(header_values(headers, 'vgs-upstream-status-code'))
    upstream_status = next(iter(upstream_statuses)) if len(upstream_statuses) == 1 else ''
    evidence = {
        'httpStatus': status if type(status) is int and 100 <= status <= 599 else None,
        'vgsRequestIdPresent': any(header_values(headers, 'vgs-request-id')),
        'vgsUpstreamPresent': any(header_values(headers, 'vgs-upstream')),
        'vgsUpstreamStatusCode': int(upstream_status) if re.fullmatch(r'[1-5][0-9]{2}', upstream_status) else None,
        'vgsUpstreamResponseTimePresent': any(header_values(headers, 'vgs-upstream-response-time')),
        'cacheEvidence': cache_evidence(entry, res),
    }
    size = res.get('_transferSize')
    if type(size) is int and size >= 0:
        evidence['transferBytes'] = size
    body = req.get('postData') if stage == 'encrypt' else res.get('content')
    info, data = body_info(body)
    evidence['bodyAvailability'] = info['availability']
    if stage == 'bridge-sdk':
        directives = {d.strip() for value in header_values(headers, 'cache-control')
                      for d in value.split(',')}
        evidence['cacheControlNoStorePrivate'] = directives == {'no-store', 'private'}
        evidence['sdkPatchMarker'] = 'unknown'
        if data:
            marker = (b'const awgCsCard=e&&e.CARD,awgCsStandins=' in data and
                      b'return Promise.resolve("AWGCS1:"' in data)
            evidence['sdkPatchMarker'] = 'present' if marker else 'absent-in-recorded-body'
    elif stage == 'encrypt' and route['method'] == 'POST':
        if route['path'] == '/flex/v2/tokens':
            evidence['routeLabel'] = 'flex-tokens'
            evidence['requestEnvelope'] = request_envelope(data) if data else 'unknown'
        elif route['path'] == '/book/api/bsmPayments':
            evidence['routeLabel'] = 'bsm-payments'
    return evidence


class BindingsError(ValueError):
    """Safe to display without exposing the specification or file path."""


def load_bindings(path):
    path_given = path is not None
    if path is None:
        path = Path(__file__).resolve().parent / '../../../examples/adapters/cybersource/adapter.json'
    try:
        bindings = json.loads(path.read_bytes())['bindings']
        if not isinstance(bindings, list):
            raise ValueError
        routes = []
        for binding in bindings:
            stage, when = binding['key'], binding['when']
            if stage not in ('capture', 'bridge-sdk', 'encrypt') or set(when) != {'host', 'method', 'path'}:
                raise ValueError
            host, method, route_path = when['host'], when['method'], when['path']
            label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
            if (len(host) > 253 or not re.fullmatch(rf'{label}(?:\.{label})*', host) or
                    not re.fullmatch(r'[A-Z]+', method) or
                    not re.fullmatch(r'/[^\s\x00-\x1f\x7f?#*\\]*', route_path)):
                raise ValueError
            # A list read back from VGS says whether each binding is enabled; the example's flags are placeholders.
            enabled = binding.get('enabled') if path_given else None
            if enabled not in (None, True, False):
                raise ValueError
            routes.append((stage, {**when, 'host': host.lower()}, enabled))
        return routes
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise BindingsError('Cannot read CyberSource bindings. Supply a valid --cybersource-bindings PATH.') from None


def cybersource_report(raw, bindings_path=None):
    bindings = load_bindings(bindings_path)
    entries = json.loads(raw)['log']['entries']
    stages = {stage: [] for stage, _, _ in bindings}
    for index, entry in enumerate(entries):
        req = entry.get('request', {})
        url = urlsplit(req.get('url', ''))
        route = {'host': url.hostname, 'method': req.get('method'), 'path': url.path}
        exact_stages = {stage for stage, when, _ in bindings if route == when}
        for binding_index, (stage, when, enabled) in enumerate(bindings):
            # Keep version/path and wrong-host near misses without listing unrelated traffic.
            if url.path.rstrip('/').rsplit('/', 1)[-1] != when['path'].rstrip('/').rsplit('/', 1)[-1]:
                continue
            mismatch = [key for key in route if route[key] != when[key]]
            if mismatch and stage in exact_stages:
                continue
            row = {'entry': index, 'bindingIndex': binding_index, 'mismatchedFields': mismatch}
            if enabled is not None:
                row['bindingEnabled'] = enabled
            if not mismatch:
                row.update(stage_evidence(stage, when, entry))
            stages[stage].append(row)
    return {'harSha256': sha(raw), 'entryCount': len(entries), 'stages': stages,
            'bindingsSource': 'bundled-example' if bindings_path is None else 'explicit-file',
            'scope': 'Browser HAR evidence against the selected routes. Function dispatch, session writes, '
                     'reveals and upstream encryption require correlated gateway evidence.'}


def write_private(path, data):
    # Exclusive creation avoids overwriting a private original or following a symlink.
    with path.open('xb') as handle:
        handle.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('har', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--entry', type=int)
    parser.add_argument('--extract-dir', type=Path)
    parser.add_argument('--cybersource', action='store_true',
                        help='report CyberSource stage evidence without printing captured strings')
    parser.add_argument('--cybersource-bindings', type=Path, metavar='PATH',
                        help='use an explicit route specification (implies --cybersource)')
    args = parser.parse_args()
    os.umask(0o077)
    if (args.entry is None) != (args.extract_dir is None):
        parser.error('--entry and --extract-dir must be supplied together')
    cybersource = args.cybersource or args.cybersource_bindings is not None
    if cybersource and args.extract_dir is not None:
        parser.error('--cybersource cannot be combined with extraction')
    if cybersource:
        try:
            report = cybersource_report(args.har.read_bytes(), args.cybersource_bindings)
        except BindingsError as error:
            parser.error(str(error))
        except (OSError, ValueError, KeyError, AttributeError, TypeError, RecursionError):
            parser.error('Cannot read CyberSource HAR.')
    else:
        report, entries = index_har(args.har.read_bytes())
    if args.entry is not None:
        if not 0 <= args.entry < len(entries):
            parser.error('entry index is outside the HAR')
        args.extract_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        entry = entries[args.entry]
        for name, body in [('request', entry.get('request', {}).get('postData')),
                           ('response', entry.get('response', {}).get('content'))]:
            _, data = body_info(body)
            if data is not None:
                write_private(args.extract_dir / (name + '.body'), data)
        write_private(args.extract_dir / 'metadata.json',
                      (json.dumps({'harSha256': report['harSha256'], **report['entries'][args.entry]}, indent=2) + '\n').encode())
    payload = json.dumps(report, indent=2) + '\n'
    if args.output:
        try:
            write_private(args.output, payload.encode())
        except OSError:
            parser.error('Cannot create report output.')
        print('Wrote local report.' if cybersource else f'Wrote local index: {args.output}')
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()
