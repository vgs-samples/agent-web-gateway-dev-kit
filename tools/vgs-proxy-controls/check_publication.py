"""Reject private runtime artifacts and obvious secrets before publication.

Only checked-in files (or an explicit package allowlist) are scanned. Public test
cards and synthetic authentication fixtures remain intentional source examples.
This complements, rather than replaces, a secret scanner and screenshot review.
"""
from pathlib import Path, PurePosixPath
import hashlib
import re
import subprocess


PRIVATE_NAMES = {'.proxy-controls.json', '.proxy-controls-accounts.json',
                 '.proxy-controls-egress.json', 'card.json', 'card.real.json',
                 'sites.yaml', 'service-account.yaml', 'service-account-secrets.txt'}
PRIVATE_DIRS = {'.private', 'private', '.private-extension', '.private-mcp',
                'control-panel-sessions', 'test-captures', 'har-library', '__pycache__'}
PRIVATE_TEXT = {
    'personal home directory': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'macOS temporary directory': re.compile(r'/(?:private/)?var/folders/'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{32,}'),
    'JWT credential': re.compile(r'\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{16,}'),
    'GitHub credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
}


# Exact reviewed teaching fixtures only. A renamed or edited HAR remains private.
PUBLIC_SYNTHETIC_HARS = {
    'examples/adapters/adyen/fixtures/capture.synthetic.har': '4d36277f98fa8e4aa0b76ac81ea24307951f7ec9798b12133c7b8def8018f1af',
    'examples/adapters/adyen/fixtures/encrypt.synthetic.har': '4ca19658d9b27f6e83538878ada2482b113450b00d81a72d7f6011e9ad12bde0',
    'examples/adapters/cybersource/fixtures/bridge-sdk.synthetic.har': 'c75e1e0021262af60c7fa72f7377417537e91bf2be672119915815463e3a5dd8',
    'examples/adapters/cybersource/fixtures/capture.synthetic.har': 'df14d3f8656df5ea3548bc2ff41d96bfae753e034ae11f721dffc23cc38b9036',
    'examples/adapters/cybersource/fixtures/encrypt.synthetic.har': 'f51a0ccd4a5d726435fff8789bf02f3ec38220bd6302271b72ce037baab945a9',
    'examples/adapters/oppwa/fixtures/reveal.synthetic.har': '9cd4f4b3bd4cc5c73f5e105e2a3a86c5a9689749a4159653876986021fce3726',
    'examples/adapters/stripe/fixtures/reveal.synthetic.har': 'd492cee7e1565c3edac8ba9d247a2274cf84a60ba177107f74d8b05bf223f27b',
}


def inspect_file(name, data):
    path = PurePosixPath(name)
    errors = []
    reviewed_har = PUBLIC_SYNTHETIC_HARS.get(name) == hashlib.sha256(data).hexdigest()
    if (path.name in PRIVATE_NAMES or set(path.parts) & PRIVATE_DIRS
            or any(p.startswith('.state') for p in path.parts)
            or (path.suffix == '.har' and not reviewed_har)
            or path.suffix in {'.pem', '.key', '.p12', '.pfx', '.webm', '.mp4', '.pyc'}
            or re.fullmatch(r'RS[A-Za-z0-9]+(?:\.request)?\.json', path.name)
            or path.name.endswith('.secret.json')
            or path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example')):
        errors.append('private runtime filename')
    try:
        value = data.decode('utf-8')
    except UnicodeError:
        return errors
    for label, pattern in PRIVATE_TEXT.items():
        if pattern.search(value):
            errors.append(label)
    if path.name == 'background.js' and 'const INITIAL_SESSION =' in value:
        errors.append('generated extension worker')
    if path.suffix in {'.md', '.mdx', '.rst'}:
        # The product name and the Unix null device are unrelated to environments.
        customer_text = re.sub(r'\bdev[ -]kit\b|/dev/null', '', value, flags=re.I)
        if (re.search(r'\bdev\b|allow_dev_env', customer_text, re.I)
                or re.search(r'(?:vgsapi|verygoodsecurity|verygoodproxy|verygoodvault)\.io\b', value, re.I)):
            errors.append('internal environment reference in customer documentation')
    return errors


def check_files(root, names):
    errors = []
    for name in sorted(set(names)):
        file = root / name
        if file.is_symlink() or not file.is_file():
            errors.append((name, ['missing file or symlink']))
        else:
            findings = inspect_file(name, file.read_bytes())
            if findings:
                errors.append((name, findings))
    if errors:
        # Never print the value which matched a rule.
        raise ValueError('\n'.join(name + ': ' + ', '.join(findings) for name, findings in errors))


if __name__ == '__main__':
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    check_files(root, [name for name in names if name])
    print('Public source privacy checks passed.')
