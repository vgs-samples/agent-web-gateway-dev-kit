"""Discover local AWG service accounts without exposing credentials or contacting VGS."""
import argparse
import json
import os
from pathlib import Path

from account_files import AccountFileError, read_account_file

ENVIRONMENTS = ('dev', 'sandbox', 'live')


def account_directory(environment):
    if environment not in ENVIRONMENTS:
        raise AccountFileError('Choose Dev, Sandbox, or Live.')
    root = Path(os.environ.get('AWG_HOME') or Path.home() / '.vgs' / 'awg').expanduser()
    return root.resolve() / environment


def saved_accounts(environment):
    directory = account_directory(environment)
    result = {'credentialsDirectory': str(directory), 'credentialFiles': []}
    try:
        paths = sorted(directory.iterdir())
    except FileNotFoundError:
        return result
    except OSError:
        return {**result, 'credentialsError': 'Could not list the saved credentials folder. Enter a file path directly.'}
    for path in paths:
        if path.suffix.lower() not in ('.env', '.json', '.yaml', '.yml', '.txt') and not path.name.startswith('.env'):
            continue
        try:
            # No recursion, symlinks or devices; account_files also bounds reads to 64 KB.
            if path.is_symlink() or not path.is_file():
                continue
            read_account_file(str(path), environment, allow_unresolved=True)
        except (AccountFileError, OSError):
            continue
        result['credentialFiles'].append({'name': path.name, 'path': str(path)})
    return result


def default_account(environment):
    listing = saved_accounts(environment)
    files = listing['credentialFiles']
    canonical = account_directory(environment) / (environment + '.env')
    if any(item['path'] == str(canonical) for item in files):
        return canonical
    if len(files) == 1:
        return Path(files[0]['path'])
    raise AccountFileError('Choose a saved credentials file or enter its path. Use ./awg credentials to list saved accounts.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', nargs='?', choices=ENVIRONMENTS)
    args = parser.parse_args()
    for environment in (args.environment,) if args.environment else ENVIRONMENTS:
        listing = saved_accounts(environment)
        print(f"{environment}: {json.dumps(listing['credentialsDirectory'])}")
        for item in listing['credentialFiles']:
            print('  ' + json.dumps(item['name']))
        if listing.get('credentialsError'):
            print('  ' + listing['credentialsError'])
        elif not listing['credentialFiles']:
            print('  (no saved credentials)')


if __name__ == '__main__':
    main()
