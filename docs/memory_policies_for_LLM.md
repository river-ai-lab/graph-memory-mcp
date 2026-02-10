# Agent Memory Directives

**Role**: You are an autonomous agent or sub-agent with access to a **Long-Term Graph Memory**.
**Purpose**: This memory is your **Knowledge Base**, not a chat log. It persists across sessions and can be shared with other agents.

## core Principles

1.  **Immutability of Intent**: Store *what* was decided/learned, not *how* it was discussed.
2.  **High Signal-to-Noise**: Only committed, verified facts belong here.
3.  **Agent Coordination**: Your memory may be read by other agents. Be clear, structured, and context-aware.

## 1. What to Store (Long-Term Knowledge)

Store information that has **strategic value** for future tasks or other agents.

-   **✅ World State**: "The production database is located at host X." (Persistent environmental facts).
-   **✅ User Alignment**: "User priority is speed over cost." (Preferences, Goals, Constraints).
-   **✅ Tool Competence**: "To restart the service, sequence Y is required." (Learned workflows/solutions).
-   **✅ Entity Relations**: "Service A depends on Service B." (Structural knowledge).
-   **✅ Summarized Outcomes**: "Research on topic Z concluded that approach A is optimal." (Synthesis).

## 2. What NOT to Store (Noise & Risk)

-   **❌ Chat Logs**: Never store raw conversation history ("Hello", "User asked...", "I replied...").
-   **❌ Ephemeral Context**: "Processing file X...", "Let me think...", "Error on line 5 (fixed)".
-   **❌ Secrets**: **NEVER** store API keys, passwords, tokens, or PII.
-   **❌ Intermediate Reasoning**: Do not store Chain-of-Thought (CoT) or scratchpad notes unless they are a final lesson learned.

## 3. Operational Rules

### Context & Isolation (`owner_id`)
-   **Private Memory**: Use `owner_id='agent:{your_id}'` (Convention).
-   **Shared Knowledge**: Use `owner_id='team:{team_id}'` (Convention). *Note: The system does not enforce robust permissions; "sharing" means agreeing on the same ID.*
-   **User Specific**: Use `owner_id='user:{user_id}'`.

### Maintenance
-   **Update Protocol** (Manual):
    1.  Call `mark_outdated(fact_id=..., reason="Changed in v2")`.
    2.  Call `create_node(text="New fact...")`.
    *Do not overwrite history unless correcting a typo.*
-   **Search First**: Avoid duplication by searching before writing.

## 4. Fact Structure (JSON Metadata)

Use `metadata` to store structured context. **Note: Metadata is currently retrieved with the node but is NOT efficiently searchable/filterable yet.**

```json
{
  "type": "regulation",
  "confidence": 0.95,
  "source": "https://api.docs...",
  "tags": ["critical"]
}
```
