#!/usr/bin/env python3
"""Run the shareable DEV proxy controls with your own private session files."""
import sys

if sys.version_info < (3, 10):
    print('Python 3.10 or newer is required.', file=sys.stderr)
    raise SystemExit(1)

import argparse
import json
import os
from pathlib import Path
import threading

from awg_dev_api import Client
from session_catalog import Catalog, CatalogServer, alive, session_config
from session_proxy_extension import write_extension


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, type=Path, help='Original saved DEV reveal-session creation response')
    parser.add_argument('--credentials-file', required=True, type=Path, help='Private DEV environment file; see dev.env.example')
    parser.add_argument('--sessions-dir', type=Path, help='Directory of RS….json creation responses and matching .request.json files')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / '.private-extension', help='Private generated extension directory')
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
        config = session_config(session_path, document['data']['attributes']['proxy']['ca_bundle'])
        client = Client(args.credentials_file.expanduser().resolve())
        if args.check:
            print('Local DEV inputs valid. No network requests made.')
            return 0
        if output.exists() and any(output.iterdir()) and not (output / '.proxy-controls-generated').is_file():
            raise ValueError('Choose an empty output directory')
        catalog = Catalog(session_path, client=client, sessions_directory=args.sessions_dir or session_path.parent)
        server = CatalogServer(session_path, catalog=catalog)
        write_extension(output, config['pacUrl'], config['credentials'], config['proxies']['session'],
                        config['proxies']['egress'], session_id=config['sessionId'],
                        expires_at=config['expiresAt'], catalog=server.config)
        marker = output / '.proxy-controls-generated'
        marker.write_text('Private generated extension; do not share this directory.\n')
        marker.chmod(0o600)
        print('DEV proxy controls are ready. Keep this Terminal open.', flush=True)
        print('In your test browser: Extensions → Developer mode → Load unpacked.', flush=True)
        print('Select this private directory: ' + str(output), flush=True)
        print('If already loaded, click Reload for VGS Proxy Controls.', flush=True)
        print('Open VGS Proxy Controls from the extensions menu. Ctrl-C stops the local helper.', flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        print('\nLocal session helper stopped. Restart this command and reload the extension to reconnect.')
    except Exception:
        # Session JSON, API errors and URLs can contain secrets. Never print them.
        print('Setup could not complete. Check Python version, active DEV session, credentials file, matching egress request file, and output directory. See README.md.', file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
