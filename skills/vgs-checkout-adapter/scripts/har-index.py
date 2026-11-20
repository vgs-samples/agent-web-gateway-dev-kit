#!/usr/bin/env python3
"""Index a private HAR without printing headers, query strings or body values.

Paths can still contain identifiers. This tool is not a sanitizer.
"""
import argparse
import base64
import hashlib
import json
import os
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
    args = parser.parse_args()
    os.umask(0o077)
    if (args.entry is None) != (args.extract_dir is None):
        parser.error('--entry and --extract-dir must be supplied together')
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
        write_private(args.output, payload.encode())
        print('Wrote local index:', args.output)
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()
