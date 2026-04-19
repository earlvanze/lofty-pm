# Property `UPDATES.md` schema

Canonical file path:
- `<Property>/Public/Updates/UPDATES.md`

Canonical entry format:

```md
# Property Updates

## 2026-03-31

- Property Update (03/31/2026):
  Clean text here. No source/status in the actual owner email body.
```

Rules:
- newest entry goes at the top
- use one canonical header line exactly:
  - `- Property Update (MM/DD/YYYY):`
- body text should be clean, human-readable update text only
- do not include `source:` / `status:` in the email-facing update body
- `lofty-vp-comms` should read the latest dated entry and map it to:
  - `patch.updates` for `update-manager-property`
  - `updatesDiff` for `send-property-updates`
