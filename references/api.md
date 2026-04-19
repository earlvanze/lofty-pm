# Lofty PM property-page update APIs

Derived from HAR captures and direct Brave CDP runtime interception.

## Supported endpoints
- `GET /prod/property-managers/v2/get-manager-properties`
- `POST /prod/property-managers/v2/update-manager-property`
- `POST /prod/property-managers/v2/send-property-updates`

## Authentication model
- Auth is SigV4 and endpoint-specific.
- Do not reuse auth captured for one endpoint on a different endpoint.
- Preferred runtime model: refresh exact endpoint auth on demand from the live authenticated Brave CDP Lofty tab.
- Retry once automatically on 403/signature/expiry, then fail loudly.

## Direct Brave CDP policy
- Use `127.0.0.1:9222` only.
- Do not use browser relay.
- Reuse an existing authenticated Lofty tab when possible.
- Prefer one canonical Lofty tab.
- Avoid duplicate tabs for the same property.
- Only open a new Lofty tab if none reusable exists.
- Optionally close extra Lofty tabs at run start/end.

## Send-update trigger
- `send-property-updates` can be triggered through Lofty’s loaded runtime wrapper (`managerSendPropertyUpdates`) when passive reload capture is insufficient.
- This makes owner-update email sending deterministic without hunting for hidden UI controls.


## Canonical tab split
- `get-manager-properties` should use/reuse a canonical Lofty list tab at `/property-owners`.
- `update-manager-property` should use/reuse a property-specific edit tab at `/property-owners/edit/{propertyId}`.
- `send-property-updates` should use/reuse the same property-specific edit tab/runtime as save.
- Keep one canonical list tab and one canonical active edit tab when possible; avoid duplicate Lofty tabs.
