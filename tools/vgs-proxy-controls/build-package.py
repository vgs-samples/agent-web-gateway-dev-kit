#!/usr/bin/env python3
"""Build only public source files; never recurse into private runtime directories."""
from pathlib import Path
import hashlib
import zipfile

FILES = [
    'README.md', 'dev.env.example', '.gitignore', 'build-package.py',
    'start-proxy-controls.py', 'awg_dev_api.py', 'session_catalog.py',
    'session_proxy_extension.py', 'test_session_catalog.py',
    'test_session_proxy_extension.mjs', 'test_session_proxy_browser.py',
    'session-proxy-extension/background.js', 'session-proxy-extension/popup.html',
    'session-proxy-extension/popup.js', 'session-proxy-extension/popup.css',
]


def build(root=None, output=None):
    root = Path(root or Path(__file__).resolve().parent)
    output = Path(output or root / 'dist/vgs-proxy-controls-1.3.0.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'vgs-proxy-controls-1.3.0/'
    checksums = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Missing or symlinked public source: ' + name)
            data = path.read_bytes()
            if name == 'session-proxy-extension/background.js' and b'const INITIAL_SESSION =' in data:
                raise ValueError('Use the source template, not a generated private worker')
            archive.writestr(prefix + name, data)
            checksums.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr(prefix + 'SHA256SUMS', '\n'.join(checksums) + '\n')
    print(str(output))
    return output


if __name__ == '__main__':
    build()
