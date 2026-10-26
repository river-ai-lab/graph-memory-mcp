# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- Security: where `/mcp` has no credential (`client`, `header` without `ADMIN_TOKEN`), a loopback `Host` from a non-loopback peer gets HTTP 421 instead of passing the Host allowlist.
- Security: `OWNER_SCOPE=client` refuses to start on a non-loopback bind (`0.0.0.0`, `::`, LAN IP), since `/mcp` has no authentication there. `ALLOW_INSECURE_CLIENT=1` warns and starts anyway. The Docker image needs `OWNER_SCOPE=token` or that opt-in.

## [0.2.1] - 2026-10-26

- `get_context` paging: `has_more` is true only when the next page has visible nodes. Hidden outdated neighbors no longer produce an empty next page. A last full page now reports `has_more` false. Default calls (no `page`, `offset=0`) are unchanged.
- `export_owner` paging: `has_more` is true only when another row exists. An exactly full last page now reports `has_more` false. Unpaged exports are unchanged.
- `export_owner` paging with `include_versions=false`: versions are filtered before `SKIP`/`LIMIT`, so pages no longer repeat rows or stall.
- Docs: ArcadeDB 26.10+ is required (compose pins `26.10.2`); `--auth` needs `ADMIN_TOKEN`; the `mcp>=2.3` Python client is `streamable_http_client`; `get_context` hides outdated neighbors unless `include_outdated=true`.
- MCP 2 (`mcp>=2.3`).
- `--auth` (`OWNER_SCOPE=token`): the API key picks the owner. Tool schemas omit `owner_id`.
