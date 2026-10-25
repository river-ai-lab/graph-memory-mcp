# Contributing to Graph Memory MCP

Contributions are welcome. This document covers development setup, testing, and pull request guidelines.

## Development setup

1. **Install dependencies** with [uv](https://github.com/astral-sh/uv):

   ```bash
   uv sync
   ```

   This installs runtime dependencies and the `dev` group (pre-commit, pytest, ruff).

2. **Install pre-commit hooks**:

   ```bash
   uv run pre-commit install
   ```

   Hooks run automatically on `git commit` and include:
   - trailing-whitespace, end-of-file-fixer
   - yaml/json/toml checks
   - ruff check and format

3. **Start databases**:

   ```bash
   cp env.example .env
   docker compose up -d
   ```

   This starts ArcadeDB (port 2480) and FalkorDB (port 6379).

## Running tests

**Full suite** (requires running databases):

```bash
./scripts/test.sh
```

Or directly:

```bash
docker compose up -d
uv run pytest -q
```

**Backend-specific tests**:

```bash
GRAPH_BACKEND=arcadedb uv run pytest -m arcade
GRAPH_BACKEND=falkordb uv run pytest -m "not arcade"
```

Tests not marked `arcade` still need FalkorDB. No marker skips the database.

## Code style

- **Formatting**: `uv run ruff format .`
- **Linting**: `uv run ruff check . --fix`
- **Pre-commit**: `uv run pre-commit run --all-files`

All checks must pass before merging.

## Pull request guidelines

1. **Branch naming**: Use descriptive names (e.g., `fix-dedup-threshold`, `add-bm25-search`).

2. **Commit messages**: Write clear, imperative titles (e.g., "Add compact recall to search", "Fix relation policy enforcement").

3. **Tests**: Add or update tests for new features and bug fixes. Ensure `./scripts/test.sh` passes.

4. **Documentation**: Update README.md, docs/, or docstrings if the change affects user-facing behavior.

5. **Pre-commit hooks**: Run `uv run pre-commit run --all-files` before pushing.

6. **Keep PRs focused**: One feature or fix per PR. Split large changes into smaller, reviewable pieces.

7. **Describe the change**: In the PR description, explain what changed, why, and how to test it.

## Project structure

- `graph_memory_mcp/`: Core MCP server and handlers
  - `server.py`: Default profile (nested source provenance)
  - `server_simple.py`: Simple profile (flat provenance)
  - `server_extended.py`: Extended profile (collections, sharing, node types)
  - `graph_memory/`: Graph operations, backends, deduplication, search ranking
  - `cli.py`: CLI entry point
- `tests/`: pytest suite
- `docs/`: Documentation (comparison, roadmap, memory policies, features)
- `examples/`: Client configuration examples
- `assets/demo/`: Demo generation and recording
- `scripts/`: Helper scripts (test.sh, backup.sh)

## Reporting issues

Open an issue on GitHub with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs or error messages
- Environment details (OS, Python version, backend)

## Questions and discussions

Use GitHub Discussions for questions, feature requests, and general discussion.

---

Thank you for contributing!
