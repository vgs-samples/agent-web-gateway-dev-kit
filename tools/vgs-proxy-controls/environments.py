"""Explicit environment profiles. No credential or endpoint fallbacks between them."""
from pathlib import Path
import re
import urllib.request
from awg_dev_api import Client, NoRedirect

ENVIRONMENTS = {
    'dev': {'label': 'Dev', 'api': 'https://sandbox.vgsapi.io', 'authHost': 'auth.verygoodsecurity.io',
            'proxySuffix': 'sandbox.verygoodproxy.io', 'proxyPort': 3443, 'vaultSuffix': 'sandbox.vault-api.verygoodvault.io'},
    'sandbox': {'label': 'Sandbox', 'api': 'https://sandbox.vgsapi.com', 'authHost': 'auth.verygoodsecurity.com',
                'proxySuffix': 'sandbox.verygoodproxy.com', 'proxyPort': 8443, 'vaultSuffix': 'sandbox.vault-api.verygoodvault.com'},
    'live': {'label': 'Live', 'api': 'https://vgsapi.com', 'authHost': 'auth.verygoodsecurity.com',
             'proxySuffix': 'live.verygoodproxy.com', 'proxyPort': 8443, 'vaultSuffix': 'live.vault-api.verygoodvault.com'},
}


def domains(environment, tenant=None):
    spec = ENVIRONMENTS[environment]
    tenant = tenant or '{tenant}'
    return {'api': spec['api'], 'auth': 'https://' + spec['authHost'] + '/auth/realms/vgs/protocol/openid-connect/token',
            'proxy': f"https://{tenant}.{spec['proxySuffix']}:{spec['proxyPort']}",
            'vault': f"https://{tenant}.{spec['vaultSuffix']}"}


class EnvironmentClient(Client):
    def __init__(self, env_file, environment, tenant=None, *, allow_unresolved=False):
        from account_files import read_account_file
        self.env = read_account_file(str(env_file), environment, tenant, allow_unresolved=allow_unresolved)
        self.tenant_candidates = self.env.pop('_TENANTS')
        self.credentials_file = str(Path(env_file).expanduser().resolve())
        self.environment, self.tenant = environment, self.env['VGS_TENANT']
        self.opener = urllib.request.build_opener(NoRedirect())
        self.access_token, self.deadline = None, 0
