"""Dashboard create-session fields, validated before any remote request."""
import ipaddress
import re


def validate_egress(value):
    if not isinstance(value, dict) or set(value) - {'type','scheme','hostname','port','username','password'}:
        raise ValueError('Invalid egress fields')
    host = value.get('hostname', '')
    port = value.get('port')
    user, password = value.get('username', ''), value.get('password', '')
    if (value.get('scheme') not in ('http', 'https') or not isinstance(host, str)
            or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', host)
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(user, str) or not isinstance(password, str)
            or bool(user) != bool(password) or ':' in user or len(user) > 1024 or len(password) > 4096):
        raise ValueError('Check the egress host, port, and paired user name/password')
    return {'type':'custom', 'scheme':value['scheme'], 'hostname':host.lower(), 'port':port,
            **({'username':user, 'password':password} if user else {})}


def validate_aliases(rows, environment):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError('Add between 1 and 20 aliases')
    prefix = 'tok_live_' if environment == 'live' else 'tok_sandbox_'
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'alias','format','bin','length','storage'}:
            raise ValueError('Unsupported alias fields')
        alias, fmt, storage = row.get('alias'), row.get('format'), row.get('storage')
        if not isinstance(alias, str) or not re.fullmatch(prefix + r'[A-Za-z0-9_]{8,200}', alias):
            raise ValueError('Enter a ' + prefix + ' alias, never a raw card value')
        if fmt not in ('card_number','card_cvc','text') or storage not in ('PERSISTENT','VOLATILE'):
            raise ValueError('Choose an alias format and storage')
        out = {'alias':alias, 'format':fmt, 'storage':storage}
        if fmt == 'card_number':
            if storage != 'PERSISTENT': raise ValueError('Card number aliases must use Persistent storage')
            if not isinstance(row.get('bin'), str) or not re.fullmatch(r'\d{6}(?:\d{2})?', row['bin']):
                raise ValueError('Card number aliases need a 6 or 8 digit BIN')
            out['bin'] = row['bin']
        elif row.get('bin'): raise ValueError('BIN applies only to card number aliases')
        if fmt == 'card_cvc' and storage != 'VOLATILE': raise ValueError('Security code aliases must use Volatile storage')
        if fmt != 'text':
            length = row.get('length', 16 if fmt == 'card_number' else 3)
            if type(length) is not int or length not in (range(13,20) if fmt == 'card_number' else (3,4)):
                raise ValueError('Check the card number or security code length')
            out['length'] = length
        elif row.get('length') is not None: raise ValueError('Text aliases do not have a card length')
        result.append(out)
    if len({r['alias'] for r in result}) != len(result): raise ValueError('Each alias may be added only once')
    formats = {r['format'] for r in result}
    if ('card_number' in formats) != ('card_cvc' in formats):
        raise ValueError('Include both card number and security code aliases')
    return result


def validate_dashboard_options(value, environment):
    allowed = {'requestId','aliases','allowedHosts','allowedClientCidrs','adapter','egressMode','egress'}
    if not isinstance(value, dict) or set(value) - allowed: raise ValueError('Unsupported session fields')
    if not isinstance(value.get('requestId'), str) or not re.fullmatch(r'[a-f0-9-]{36}', value['requestId']):
        raise ValueError('Invalid request ID')
    aliases = validate_aliases(value.get('aliases'), environment)
    hosts = value.get('allowedHosts', [])
    if not isinstance(hosts, list) or len(hosts) > 20: raise ValueError('Use up to 20 exact hostnames')
    normalized = []
    for host in hosts:
        if not isinstance(host, str): raise ValueError('Invalid hostname')
        host = host.lower().rstrip('.')
        if len(host)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*',host):
            raise ValueError('Use exact hostnames without a scheme, port or wildcard')
        if host not in normalized: normalized.append(host)
    cidrs = value.get('allowedClientCidrs', [])
    if not isinstance(cidrs, list) or len(cidrs)>10: raise ValueError('Use up to 10 client addresses or ranges')
    clients=[]
    for cidr in cidrs:
        if not isinstance(cidr,str): raise ValueError('Invalid client address')
        try: network=str(ipaddress.ip_network(cidr, strict=False))
        except ValueError: raise ValueError('Enter valid client IP addresses or CIDR ranges') from None
        if network not in clients: clients.append(network)
    adapter=value.get('adapter','')
    if not isinstance(adapter,str) or adapter and not re.fullmatch(r'AD[A-Za-z0-9]+',adapter): raise ValueError('Invalid adapter')
    mode=value.get('egressMode','profile')
    if mode not in ('profile','custom','none'): raise ValueError('Choose an egress type')
    egress=validate_egress(value.get('egress')) if mode=='custom' else None
    if mode!='custom' and value.get('egress') is not None: raise ValueError('Unexpected egress fields')
    return {'requestId':value['requestId'], 'source':'dashboard', 'aliases':aliases, 'allowedHosts':normalized,
            'allowedClientCidrs':clients, 'adapter':adapter, 'egressMode':mode, 'egress':egress}
