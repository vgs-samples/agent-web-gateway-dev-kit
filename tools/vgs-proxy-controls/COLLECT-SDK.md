# Bundled VGS Collect SDK

Unmodified VGS Collect 4.0.1 distribution files, downloaded from the official CDN on 2026-11-18. They are bundled locally because Manifest V3 does not allow remote scripts in extension pages. VGS continues to host the secure input iframes. No SDK plugins are loaded.

- `vgs-collect-4.0.1.js`: https://js.verygoodvault.com/vgs-collect/4.0.1/vgs-collect.js
  SHA-256: `a0d750fcdd220a19e158eb5aa992d3fc0e5470c7c36e7730cdbad9e03b0d8544`

Sandbox and Live use the `.com` distribution, with sandbox/live vaults respectively. The SDK copyright header is retained. Rerun the browser checks after updating bundled SDK files.

The helper provides a transient OAuth access token only on the authenticated, tenant- and operation-bound `/collect-token` route. Client secrets stay local. The panel never puts the access token into storage, panel state, or operation journals. Its scope is inherited from the configured service account; it is not a separately downscoped Collect-only token. Card inputs are visible hosted frames (`hideValue: false`), as requested. Screen/video captures can include entered values. Accounts with aliases:write use createAliases; otherwise cards:write/cards:create uses createCard with hosted expiry. Both aliases are required; existing-card responses without a CVC alias are rejected. UUID aliases are required; PAN is PERSISTENT and CVC is VOLATILE. Response errors are never reflected verbatim.

The Sandbox test-card buttons match the dashboard’s three public fixtures and initialize hosted fields with the SDK’s `defaultValue` property. Choosing a preset remounts the fields, resets lengths to 16/3, and uses December of the current year plus three for expiry. No other values are accepted as presets; Live ignores preset requests. Preset selection does not request authorization or submit the form. Selection is not persisted.
