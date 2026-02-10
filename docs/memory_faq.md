# Long-term Memory FAQ

## Search vs. Summary?
- **“What do we know about Y?”**: Use `search(query="Y")` followed by `create_summary_fact` if you assume synthesis.
- **“Find all about Z”**: Use `search(query="Z", limit=50)` + `get_context` for raw retrieval.

## Deleting Knowledge ("Forget")
- **User Data**: Soft delete via `mark_outdated(status="outdated")`. Hard delete only for compliance/privacy.
- **Shared Data**: Generally **immutable**. Do not delete unless it's a correction.

## Fact Lifecycle & Status
- **`active`**: Default. Visible in search.
- **`outdated`**: Soft-deleted. Hidden from search (unless `include_outdated=True`). Use when knowledge changes.
- **`archived`**: Moved to cold storage by background jobs.

## Metadata Schema
Recommended structure for `metadata` dict:
- `type`: Category (e.g., "incident", "terminology").
- `entities`: List of key names (["Redis", "Auth"]).
- `tags`: Filters (["infra", "prod"]).
- `valid_until`: "YYYY-MM-DD" for expiry.

## Do we save everything?
**No.** Only explicit savings or final decisions.
- **Save**: "The server IP is 10.0.0.1", "User prefers concise answers".
- **Ignore**: "Hello", "Let me think", "Did that work?".

## Is memory shared?
- **Physically**: One database.
- **Logically**: Partitioned by `owner_id`.
- **Rule**: Always set `owner_id` to respect boundaries (private vs team).
