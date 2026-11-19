"""Read service-account files locally. Never evaluate their contents or return secrets."""
import json
import os
from pathlib import Path
import re
import stat


class AccountFileError(ValueError):
    """Only fixed, safe messages intended for the control panel."""


def cli_yaml(content):
    """Read the CLI's ServiceAccount envelope (scalar credentials + vault list).

    This deliberately does not execute YAML tags or expand aliases. Other document
    sections, such as scopes, are not needed to load a service account.
    """
    lines = content.splitlines()
    if len(re.findall(r'^kind:\s*ServiceAccount\s*$', content, re.M)) != 1:
        raise ValueError('Expected one CLI ServiceAccount document')
    data_lines = [i for i,line in enumerate(lines) if line.strip() == 'data:' and not line.startswith((' ', '\t'))]
    if len(data_lines) != 1: raise ValueError('Expected one data section')
    def scalar(value):
        value=value.strip()
        if value.startswith('"'): return json.loads(value)
        if value.startswith("'"):
            if not value.endswith("'"): raise ValueError('Invalid quoted scalar')
            return value[1:-1].replace("''", "'")
        value=re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        if not value or value[0] in '!&*|>{[': raise ValueError('Unsupported scalar')
        return value
    raw, indent, vault_mode = {}, None, False
    for line in lines[data_lines[0]+1:]:
        if not line.strip() or line.lstrip().startswith('#'): continue
        if not line.startswith(' '): break
        current_indent=len(line)-len(line.lstrip(' '))
        if indent is None: indent=current_indent
        stripped=line.strip()
        if vault_mode and stripped.startswith('- ') and current_indent >= indent:
            raw['vaults'].append(scalar(stripped[2:])); continue
        if current_indent != indent: continue
        key,sep,value=stripped.partition(':')
        vault_mode=False
        if not sep: continue
        if key == 'vaults':
            if 'vaults' in raw: raise ValueError('Duplicate vaults')
            raw['vaults']=[]
            if value.strip() and value.strip() != '[]':
                inline=value.strip()
                if not (inline.startswith('[') and inline.endswith(']')): raise ValueError('Invalid vault list')
                raw['vaults']=[scalar(v) for v in inline[1:-1].split(',') if v.strip()]
            else: vault_mode=True
        elif key in ('clientId','clientSecret','client_id','client_secret','tenantId','tenant_id','environment'):
            if key in raw: raise ValueError('Duplicate credential')
            raw[key]=scalar(value)
    return raw


def read_account_file(filename, environment, tenant=None, *, allow_unresolved=False):
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 4096:
        raise AccountFileError('Enter the full local path to the service-account file.')
    path = Path(filename).expanduser()
    if not path.is_absolute():
        raise AccountFileError('Use an absolute file path or a path starting with ~/.')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise AccountFileError('Choose a regular credentials file smaller than 64 KB.')
            content = stream.read(65537)
    except (OSError, UnicodeError):
        raise AccountFileError('The helper could not read that local file. Check its path and file permissions.') from None
    try:
        if content.lstrip().startswith('{'):
            raw = json.loads(content)
            if not isinstance(raw, dict): raise ValueError()
            if 'data' in raw:
                if raw.get('kind') not in (None, 'ServiceAccount') or not isinstance(raw['data'],dict): raise ValueError()
                raw=raw['data']
                if 'attributes' in raw: raw=raw['attributes']
                if not isinstance(raw,dict): raise ValueError()
        elif re.search(r'^kind:\s*ServiceAccount\s*$', content, re.M):
            raw=cli_yaml(content)
        else:
            raw = {}
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith('#'): continue
                if line.startswith('export '): line = line[7:].strip()
                key, value = line.split('=', 1)
                value = value.strip()
                if len(value) >= 2 and value[0] in '\"\'' and value[-1] == value[0]: value = value[1:-1]
                key = key.strip()
                if key in raw: raise ValueError()
                raw[key] = value
        def field(*names):
            found = [raw[name] for name in names if raw.get(name) is not None]
            if any(not isinstance(value, str) for value in found) or len(set(found)) > 1: raise ValueError()
            return found[0] if found else None
        vaults=raw.get('vaults', [])
        if not isinstance(vaults,list) or any(not isinstance(v,str) or not re.fullmatch(r'tnt[A-Za-z0-9]+',v) for v in vaults): raise ValueError()
        if tenant and vaults and tenant not in vaults:
            raise AccountFileError('Choose a tenant listed in this service account’s vaults.')
        file_tenant = field('VGS_TENANT', 'tenant_id', 'tenantId') or (vaults[0] if len(vaults)==1 else None)
        if tenant and file_tenant and tenant != file_tenant:
            raise AccountFileError('The tenant ID does not match the file. Clear the field to use the file’s tenant.')
        tenant = file_tenant or tenant
        if tenant is not None and (not isinstance(tenant, str) or not re.fullmatch(r'tnt[A-Za-z0-9]+', tenant)):
            raise AccountFileError('Invalid tenant metadata in the credentials file.')
        if tenant is None and not allow_unresolved:
            raise AccountFileError('A tenant ID is required for this command. Connect the file in the control panel to detect it automatically.')
        file_env = field('VGS_ENVIRONMENT', 'environment')
        if file_env and file_env.lower() != environment:
            raise AccountFileError('This file belongs to a different environment. Select its environment first.')
        from environments import domains
        expected = domains(environment)
        api, auth = field('VGS_API', 'api'), field('VGS_AUTH_URL', 'auth_url')
        if (api and api != expected['api']) or (auth and auth != expected['auth']):
            raise AccountFileError('This file belongs to a different environment. Select its environment first.')
        client_id = field('VGS_CLIENT_ID', 'client_id', 'clientId')
        client_secret = field('VGS_CLIENT_SECRET', 'client_secret', 'clientSecret')
        if not client_id or not client_secret or len(client_id) > 4096 or len(client_secret) > 8192:
            raise AccountFileError('The file must include a client ID and client secret.')
        return {'_TENANTS': list(dict.fromkeys(vaults or ([file_tenant] if file_tenant else []))), 'VGS_TENANT':tenant, 'VGS_API':expected['api'], 'VGS_AUTH_URL':expected['auth'],
                'VGS_CLIENT_ID':client_id, 'VGS_CLIENT_SECRET':client_secret}
    except AccountFileError: raise
    except (ValueError, TypeError, KeyError):
        raise AccountFileError('Use a dashboard credentials export, CLI ServiceAccount YAML/JSON, or a KEY=value credentials file.') from None


def discover_tenants(client):
    """Discover candidates; session-read authorization still gates connection.

    Claims are metadata from a token fetched over TLS from the configured auth
    server, not a replacement for API authorization checks.
    """
    import base64
    try:
        token = client.token()
    except Exception:
        raise AccountFileError('Authentication failed. Check the file and selected environment.') from None
    candidates = list(client.tenant_candidates)
    if not candidates:
        try:
            claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
            tenant = claims.get('clientAnnotations', {}).get('vgs.io/vault-id')
            if isinstance(tenant, str) and re.fullmatch(r'tnt[A-Za-z0-9]+',tenant): candidates.append(tenant)
        except (ValueError, TypeError, IndexError, AttributeError): pass
    if candidates:
        return [{'tenantId':tenant, 'name':tenant} for tenant in sorted(set(candidates))]
    raise AccountFileError('No tenant ID is included in this service account. Use a tenant-scoped account or its CLI credentials export.')
