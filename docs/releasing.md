# Releasing

`project.version` in `pyproject.toml` is the only version source. `graph_memory_mcp.__version__` reads it from the installed distribution (`importlib.metadata`) and is `0.0.0` when the checkout is not installed. Do not add a second version constant.

The package long description is `README_pypi.md`. `README.md` keeps relative links for GitHub. Those links do not resolve on PyPI, so the published description is the short file with absolute GitHub URLs.

Publishing uses GitHub Actions OIDC. Do not create a PyPI or TestPyPI API token.

## One-time: PyPI

The project is not on PyPI yet, so register a pending publisher. It creates the project on the first upload.

1. Sign in at <https://pypi.org/manage/account/publishing/>.
2. Add a GitHub Actions pending publisher:
   - PyPI Project Name: `graph-memory-mcp`
   - Owner: `river-ai-lab`
   - Repository name: `graph-memory-mcp`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

If the project name is already registered, open that project's Publishing page and add the same publisher there instead of a pending publisher.

## One-time: TestPyPI

TestPyPI has its own account database.

1. Sign in at <https://test.pypi.org/manage/account/publishing/>.
2. Add a GitHub Actions pending publisher:
   - PyPI Project Name: `graph-memory-mcp`
   - Owner: `river-ai-lab`
   - Repository name: `graph-memory-mcp`
   - Workflow name: `publish.yml`
   - Environment name: `testpypi`

## One-time: GitHub environments

On `river-ai-lab/graph-memory-mcp`: Settings → Environments → New environment.

Create `pypi` and `testpypi`. The names must match the workflow and the publishers above. Do not add secrets.

On `pypi`, turn on required reviewers so a person approves each upload. Leave `testpypi` without required reviewers.

## Cut a release

1. Set `version` in `pyproject.toml`. Update `CHANGELOG.md`.
2. Tag that commit. The tag is `v` plus the version string (`0.2.0` → `v0.2.0`).

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

`.github/workflows/publish.yml` runs on tags matching `v*`. It refuses the tag when it does not match `project.version`, builds the sdist and wheel with `uv build`, runs `twine check --strict`, then publishes those artifacts to TestPyPI (`testpypi`) and PyPI (`pypi`).

PyPI and TestPyPI reject a version that is already uploaded. Bump `version` before the next tag. The current version is `0.2.0`.
