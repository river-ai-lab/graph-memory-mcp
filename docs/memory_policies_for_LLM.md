# Agent Memory Directives

**Role**: You are an autonomous agent or sub-agent with access to the **Graph Memory MCP server**.
**Purpose**: This memory is a **long-term knowledge base**, not a chat log. It persists across sessions and may be shared with other agents through agreed `owner_id` scopes.

## Core Principles

1. **Store durable knowledge**: Save stable facts, decisions, constraints, and relationships that will matter later.
2. **Keep signal high**: Do not write noise, scratchpad thoughts, raw conversation, or transient execution state.
3. **Respect isolation**: Memory is logically partitioned by `owner_id`. Always write into the correct scope.
4. **Prefer explicit facts**: Store clear declarative facts, not vague summaries when a precise fact can be stored.

## 1. What to Store

Store information with strategic value for future work or agent coordination.

- **World State**: persistent environmental facts, system topology, service locations, repo conventions.
- **User Alignment**: preferences, constraints, priorities, and standing decisions.
- **Tool/Workflow Knowledge**: proven procedures that should be reused later.
- **Entity Relations**: dependencies, ownership, compatibility, and other structural links.
- **Summarized Outcomes**: validated conclusions from research or implementation work.

## 2. What Not to Store

- **Chat Logs**: never store raw dialogue such as "user asked..." or "I replied...".
- **Ephemeral State**: never store temporary execution notes such as "currently debugging..." or "processing file X".
- **Secrets or PII**: never store passwords, API keys, tokens, secrets, or personal data.
- **Intermediate Reasoning**: do not store chain-of-thought, scratchpad notes, or speculative reasoning.
- **Low-Confidence Guesses**: do not store uncertain claims as facts unless explicitly labeled in metadata.

## 3. Operational Rules for This Server

### Always Set `owner_id`

Always pass `owner_id` explicitly on reads and writes.

- Do not rely on the server default.
- If you omit `owner_id`, writes go to `default`, which may put data into the wrong memory scope.
- When updating or replacing a fact, use the same `owner_id` as the original node.

### Valid `owner_id` Format

This server accepts only alphanumeric characters plus `_`, `-`, and `@`.

Recommended conventions:

- **Private agent memory**: `agent_<agent_id>`
- **Shared team memory**: `team_<team_id>`
- **User-specific memory**: `user_<user_id>`

Examples of valid values:

- `agent_worker_7`
- `team_platform`
- `user_42`
- `team-alpha`
- `agent@planner`

Avoid values with `:` or spaces, such as `agent:123` or `team:core`.

### Search Before Create

Before writing a new fact:

1. Call `search(...)` with the same `owner_id`.
2. If needed, call `get_context(...)` on promising results.
3. Only create a new node if the fact is genuinely new or materially different.

Do not rely only on background deduplication. Agents should actively avoid writing duplicates.

### One Fact Per Node

Prefer one durable declarative fact per node.

Good:

- "Production Redis is hosted at redis.internal."
- "User prefers speed over cost."
- "Service A depends on Service B."

Bad:

- "We discussed infrastructure and maybe Redis is important."
- "Today we talked about several deployment ideas."

### Update Protocol

For substantive changes, preserve history instead of overwriting the old fact.

1. Call `mark_outdated(fact_id=..., owner_id=..., reason="...")`
2. Call `create_node(text="New fact...", owner_id=..., metadata=...)`

Use `update_node(...)` only for small corrections or metadata adjustments, such as:

- fixing a typo
- improving metadata
- updating TTL

### Metadata

Use `metadata` for structured context such as source, confidence, tags, or timestamps.

Example:

```json
{
  "type": "regulation",
  "confidence": 0.95,
  "source": "https://api.docs.example",
  "tags": ["critical"]
}
```

Note:

- Metadata is returned with the node.
- Metadata is not the main searchable/filterable surface today.
- Put the primary fact in `text`, not only in metadata.

## 4. Recommended Agent Behavior

When using Graph Memory MCP:

1. Identify the correct `owner_id` first.
2. Search before writing.
3. Store only durable, reusable knowledge.
4. Keep facts atomic and explicit.
5. When knowledge changes materially, mark the old fact outdated and create a new one.
6. Never store secrets, raw conversation, or scratchpad reasoning.
