# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- `get_context` paging: `has_more` is true only when the next page has visible nodes. Hidden outdated neighbors no longer produce an empty next page. A last full page now reports `has_more` false. Default calls (no `page`, `offset=0`) are unchanged.
- Docs: ArcadeDB 26.10+ is required (compose pins `26.10.2`); `--auth` needs `ADMIN_TOKEN`; the `mcp>=2.3` Python client is `streamable_http_client`; `get_context` hides outdated neighbors unless `include_outdated=true`.
- MCP 2 (`mcp>=2.3`).
- `--auth` (`OWNER_SCOPE=token`): the API key picks the owner. Tool schemas omit `owner_id`.
