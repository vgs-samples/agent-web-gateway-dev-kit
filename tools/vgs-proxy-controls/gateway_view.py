"""Read-only gateway configuration for the authenticated local control panel."""
from awg_dev_api import ApiError
from mcp_gateway import GatewayBridge


RESOURCES = frozenset(('agent-gateway-destinations', 'agent-gateway-adapters',
                       'functions', 'agent-gateway-adapter-destinations'))


class GatewayViewError(ValueError):
    pass


def read_configuration(registry, environment, options):
    if (not isinstance(options, dict)
            or set(options) - {'tenantId', 'resource', 'id', 'limit', 'offset'}
            or not isinstance(options.get('resource'), str)
            or options['resource'] not in RESOURCES):
        raise GatewayViewError('Choose a destination, adapter, function, or connection to view.')
    try:
        catalog = registry.get(environment)
        if not catalog:
            raise GatewayViewError('Connect a service account for this environment in Settings.')
        if not options.get('tenantId') or options['tenantId'] != catalog.tenant:
            raise GatewayViewError('The selected tenant changed. Refresh the panel and try again.')
        # Reuse the same tenant checks, ID validation and bounded pagination as MCP.
        # The operation is fixed here; panel input can never enable gateway writes.
        bridge = GatewayBridge(registry, environment, '.', allow_writes=False)
        result = bridge.execute({**options, 'operation': 'read'})
        return {'environment': environment, 'tenantId': catalog.tenant,
                'resource': options['resource'], 'id': options.get('id'), 'document': result}
    except GatewayViewError:
        raise
    except ApiError as error:
        if error.status in (401, 403):
            raise GatewayViewError('Access denied. Check agent-gateway:read permission for this tenant.') from None
        if error.status == 404:
            raise GatewayViewError('This resource is no longer available. Refresh the list.') from None
        raise GatewayViewError('Gateway configuration is unavailable. Try refreshing the list.') from None
    except ValueError:
        raise GatewayViewError('Invalid gateway selection. Refresh the list and try again.') from None
    except Exception:
        raise GatewayViewError('Could not load gateway configuration. Check the local helper and account.') from None
