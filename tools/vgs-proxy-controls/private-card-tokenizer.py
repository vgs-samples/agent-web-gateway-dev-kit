#!/usr/bin/env python3
"""Private Terminal card input; only fresh aliases leave the Unix socket."""
import argparse
import getpass
import json
import os
from pathlib import Path
import resource
import socket
import sys
import time
from urllib.request import Request

from awg_dev_api import TENANT
from environments import EnvironmentClient, ENVIRONMENTS, domains
from session_operations import validate_card


def tokenize(client, supplied, method):
    environment = getattr(client, 'environment', 'dev')
    tenant = getattr(client, 'tenant', TENANT)
    if method == 'cards':
        result = client.api('POST', '/cards', supplied, accepted=(201, 303))
        attrs = result['data']['attributes']
        if result.get('metadata', {}).get('observability', {}).get('vault_id') != tenant or attrs.get('last4') != supplied['pan'][-4:]:
            raise ValueError('Card metadata mismatch')
        pan, cvc = attrs.get('pan_alias'), attrs.get('cvc_alias')
    else:
        # Separate alias API scope; no reveal endpoint or global preference mutation.
        payload = {'data': [{'value': supplied[key], 'format': 'UUID', 'storage': storage}
                            for key, storage in [('pan', 'PERSISTENT'), ('cvc', 'VOLATILE')]]}
        request = Request(domains(environment, tenant)['vault'] + '/aliases',
                          data=json.dumps(payload).encode(), method='POST',
                          headers={'Authorization': 'Bearer ' + client.token(), 'Content-Type': 'application/json'})
        with client.opener.open(request, timeout=45) as response:
            if response.status != 201: raise ValueError('Alias creation failed')
            result = json.load(response)
        rows = result['data']
        if len(rows) != 2 or any(row.get('value') != supplied[key] or row.get('storage') != storage
                                  for row, key, storage in zip(rows, ['pan', 'cvc'], ['PERSISTENT', 'VOLATILE'])):
            raise ValueError('Alias metadata mismatch')
        pan, cvc = [next(a['alias'] for a in row['aliases'] if a['format'] == 'UUID') for row in rows]
    card = {'number': {'alias': pan, 'bin': supplied['pan'][:6], 'length': len(supplied['pan']), 'storage': 'PERSISTENT'},
            'cvc': {'alias': cvc, 'length': len(supplied['cvc']), 'storage': 'VOLATILE'}}
    validate_card(card, environment)
    return {'environment': environment, 'tenant': tenant, 'card': card}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', choices=list(ENVIRONMENTS), default='dev')
    parser.add_argument('--credentials-file', required=True, type=Path)
    parser.add_argument('--socket', required=True, type=Path)
    parser.add_argument('--method', choices=['cards', 'aliases'], default='cards')
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    if not sys.stdin.isatty(): raise ValueError('Use an interactive Terminal')
    if args.socket.exists(): raise ValueError('Tokenizer socket already exists; stop the old process first')
    client = EnvironmentClient(args.credentials_file, args.environment)
    supplied = {'pan': getpass.getpass('PAN (hidden, memory only): ').replace(' ', ''),
                'cvc': getpass.getpass('CVC (hidden, memory only): ')}
    expiry = getpass.getpass('Expiry MM/YY (hidden): ').split('/')
    supplied.update(exp_month=int(expiry[0]), exp_year=int(expiry[1]) % 100)
    if (not supplied['pan'].isdigit() or not 13 <= len(supplied['pan']) <= 19
            or not supplied['cvc'].isdigit() or len(supplied['cvc']) not in (3, 4)
            or not 1 <= supplied['exp_month'] <= 12): raise ValueError('Invalid card input')
    args.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(args.socket)); args.socket.chmod(0o600); server.listen(2); server.settimeout(1)
    print('Private card tokenizer ready for 12 hours. Keep this Terminal open; Ctrl-C clears it.', flush=True)
    deadline = time.monotonic() + 12 * 3600
    try:
        while time.monotonic() < deadline:
            try: connection, _ = server.accept()
            except socket.timeout: continue
            with connection:
                connection.settimeout(5)
                try:
                    with connection.makefile('rb') as stream: request = json.loads(stream.readline(4096))
                    if request != {'operation': 'tokenize', 'environment': client.environment, 'tenant': client.tenant}: raise ValueError('Unsupported operation')
                    response = {'ok': True, 'fixture': tokenize(client, supplied, args.method)}
                except Exception: response = {'ok': False, 'error': 'Tokenization failed. Check account scopes and card inputs.'}
                connection.sendall(json.dumps(response).encode() + b'\n')
    finally:
        supplied.clear(); server.close(); args.socket.unlink(missing_ok=True)


if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: pass
    except Exception:
        print('Tokenizer could not start. Check private file paths, card input, and Terminal access.', file=sys.stderr)
        raise SystemExit(1)
