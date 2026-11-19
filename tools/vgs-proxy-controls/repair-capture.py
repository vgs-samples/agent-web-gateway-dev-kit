#!/usr/bin/env python3
"""Diagnose a saved capture; --apply runs only repairs authorized by its local DEV policy."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from capture_repair import CaptureRepair, private_policy
from environments import EnvironmentClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--credentials-file', type=Path, required=True)
    parser.add_argument('--sessions-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        policy = private_policy(args.policy)
        client = EnvironmentClient(args.credentials_file, 'dev', policy['tenantId'])
        catalog = SimpleNamespace(client=client, tenant=policy['tenantId'], environment='dev',
                                  saved=lambda sid: args.sessions_dir/(sid+'.json'))
        registry = SimpleNamespace(get=lambda env: catalog if env == 'dev' else None)
        result = CaptureRepair(registry, args.capture.parent, args.policy).run(args.capture.stem, apply=args.apply)
        print(json.dumps(result, indent=2))
        return 0 if result['status'] in ('planned', 'repaired', 'configured', 'payment-declined') else 2
    except Exception:
        print('Repair could not complete. Check private local inputs and DEV connectivity; no automatic retry was made.')
        return 1


if __name__ == '__main__': raise SystemExit(main())
