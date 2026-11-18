#!/usr/bin/env python3
"""Run the shareable proxy controls with your own private session files."""
import sys

if sys.version_info < (3, 10):
    print('Python 3.10 or newer is required.', file=sys.stderr)
    raise SystemExit(1)

import argparse
import json
import os
from pathlib import Path
import threading

from environments import EnvironmentClient, ENVIRONMENTS
from session_catalog import Catalog, CatalogServer, alive, session_config
from session_proxy_extension import write_extension


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', choices=list(ENVIRONMENTS), default='sandbox')
    parser.add_argument('--profiles-file', type=Path, help='Private JSON mapping of additional environment profiles')
    parser.add_argument('--session', required=True, type=Path, help='Original saved reveal-session creation response')
    parser.add_argument('--credentials-file', required=True, type=Path, help='Private service-account export or environment file; see sandbox.env.example')
    parser.add_argument('--sessions-dir', type=Path, help='Directory of RS….json creation responses and matching .request.json files')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / '.private-extension', help='Private generated extension directory')
    parser.add_argument('--egress-profile', type=Path, help='Private JSON egress profile for new sessions')
    parser.add_argument('--tokenizer-socket', type=Path, help='Private card tokenizer Unix socket')
    parser.add_argument('--capture-profile', type=Path, help='Browser profile used to report sensitive-HAR preference status')
    parser.add_argument('--slot-file', type=Path, help='Optional shared session-work lock file')
    parser.add_argument('--check', action='store_true', help='Validate local inputs without starting a server or contacting VGS')
    args = parser.parse_args()
    os.umask(0o077)
    session_path = args.session.expanduser().resolve()
    output = args.output.expanduser().resolve()
    server = None
    try:
        document = json.loads(session_path.read_text())
        if not alive(document['data']['attributes']):
            raise ValueError('Session expired or revoked')
        client = EnvironmentClient(args.credentials_file.expanduser().resolve(), args.environment)
        config = session_config(session_path, document['data']['attributes']['proxy']['ca_bundle'], args.environment, client.tenant)
        profiles = json.loads(args.profiles_file.read_text()) if args.profiles_file else None
        if args.check:
            print('Local inputs valid. No network requests made.')
            return 0
        if output.exists() and any(output.iterdir()) and not (output / '.proxy-controls-generated').is_file():
            raise ValueError('Choose an empty output directory')
        catalog = Catalog(session_path, client=client, sessions_directory=args.sessions_dir or session_path.parent, egress_file=args.egress_profile,
                          tokenizer_socket=args.tokenizer_socket, capture_profile=args.capture_profile, slot_file=args.slot_file)
        server = CatalogServer(session_path, catalog=catalog, profiles=profiles)
        write_extension(output, config['pacUrl'], config['credentials'], config['proxies']['session'],
                        config['proxies']['egress'], session_id=config['sessionId'],
                        expires_at=config['expiresAt'], catalog=server.config)
        marker = output / '.proxy-controls-generated'
        marker.write_text('Private generated extension; do not share this directory.\n')
        marker.chmod(0o600)
        print('Proxy controls are ready. Keep this Terminal open.', flush=True)
        print('In your test browser: Extensions → Developer mode → Load unpacked.', flush=True)
        print('Select this private directory: ' + str(output), flush=True)
        print('If already loaded, click Reload for Agent Web Gateway Control Panel.', flush=True)
        print('Open Agent Web Gateway Control Panel from the extensions menu. Ctrl-C stops the local helper.', flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        print('\nLocal session helper stopped. Restart this command and reload the extension to reconnect.')
    except Exception:
        # Session JSON, API errors and URLs can contain secrets. Never print them.
        print('Setup could not complete. Check Python version, active session, credentials file, matching egress request file, and output directory. See README.md.', file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
