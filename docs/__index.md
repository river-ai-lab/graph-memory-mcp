# Docs

- [configuration.md](./configuration.md) — `OWNER_SCOPE` (`client`, `header`, `token`), API keys, embeddings
- [team-setup.md](./team-setup.md) — Admin: how to connect a team
- [features.md](./features.md) — API contract
- [admin.md](./admin.md) — `/admin/*`, `/internal/graph-size`, `/metrics`
- [background_jobs.md](./background_jobs.md) — archive and dedup (`JOBS_ENABLED`)
- [memory_policies_for_LLM.md](./memory_policies_for_LLM.md) — full agent policy
- [memory_policy_cheatsheet.md](./memory_policy_cheatsheet.md) — short agent sheet
- [hooks.md](./hooks.md) — client hooks that remind the agent to save memory
- [memory_faq.md](./memory_faq.md) — ops FAQ
- [roadmap.md](./roadmap.md) — unfinished work
- [comparison.md](./comparison.md) — vs other stacks
- [releasing.md](./releasing.md) — PyPI trusted publisher and version tags
- [demos.md](./demos.md) — demo recordings besides the README GIF

Explorer: [README](../README.md).

Editing the policy: change only `memory_policies_for_LLM.md`. Each rule has a `<!-- rule:<id> [scope:common] [tools:a,b] summary:"…" -->` marker; `scope:common` summaries become the MCP server instructions, `tools:` summaries are appended to those tool descriptions, and all summaries form the cheat sheet rules. Then run `python scripts/gen_policy.py` and commit the generated files (CI fails if they are stale).
