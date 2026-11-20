"""Named local egress profiles. Credentials never appear in list/save responses."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from session_form import validate_egress


class EgressProfileError(ValueError):
    """Only fixed, credential-free messages may be returned to the panel."""


class EgressProfiles:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise EgressProfileError('The local proxy file is not owned by this user.')
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return []
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise EgressProfileError('The local proxy file must be private to this user (0600).')
            try:
                doc = json.loads(stream.read(1048577))
                if doc['version'] != 1 or not isinstance(doc['profiles'], list) or len(doc['profiles']) > 100:
                    raise ValueError()
                ids, names, result = set(), set(), []
                for row in doc['profiles']:
                    if set(row) != {'id', 'name', 'proxy'} or not re.fullmatch(r'[a-f0-9]{32}', row['id']):
                        raise ValueError()
                    name = self.name(row['name'])
                    if row['id'] in ids or name.casefold() in names: raise ValueError()
                    ids.add(row['id']); names.add(name.casefold())
                    result.append({'id': row['id'], 'name': name, 'proxy': validate_egress(row['proxy'])})
                return result
            except (ValueError, KeyError, TypeError):
                raise EgressProfileError('The local proxy file is invalid. Restore it before saving another proxy.') from None

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise EgressProfileError('Enter a proxy name between 1 and 80 characters.')
        return value.strip()

    @staticmethod
    def public(row):
        proxy = row['proxy']
        return {'id': row['id'], 'name': row['name'],
                **{k: proxy[k] for k in ('scheme', 'hostname', 'port')},
                'hasAuthentication': bool(proxy.get('username'))}

    def listing(self):
        with self.locked():
            return {'egressProfiles': [self.public(row) for row in self._read()]}

    def save(self, value):
        if not isinstance(value, dict) or set(value) != {'name', 'proxy'}:
            raise EgressProfileError('Enter a name and proxy settings.')
        name = self.name(value['name'])
        try:
            proxy = validate_egress(value['proxy'])
        except ValueError:
            raise EgressProfileError('Check the proxy scheme, host, port, and paired username and password.') from None
        with self.locked():
            rows = self._read()
            if any(row['name'].casefold() == name.casefold() for row in rows):
                raise EgressProfileError('That proxy name is already saved. Choose another name.')
            if len(rows) >= 100: raise EgressProfileError('The local file already contains 100 proxies.')
            row = {'id': uuid.uuid4().hex, 'name': name, 'proxy': proxy}
            rows.append(row)
            fd, temporary = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump({'version': 1, 'profiles': rows}, stream, indent=2)
                    stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {'egressProfiles': [self.public(r) for r in rows], 'savedEgressProfileId': row['id']}

    def resolve(self, profile_id):
        if not isinstance(profile_id, str) or not re.fullmatch(r'[a-f0-9]{32}', profile_id):
            raise EgressProfileError('Choose a saved proxy from the list.')
        with self.locked():
            for row in self._read():
                if row['id'] == profile_id: return row['proxy']
        raise EgressProfileError('That saved proxy no longer exists. Refresh the proxy list.')
