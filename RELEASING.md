# Releasing Pyground

Releases are published only when the **Release to PyPI** workflow is manually
started from GitHub Actions. The requested version must exactly match the
version in `pyproject.toml`, and the workflow must be run from `main`.

## One-time trusted publishing setup

No PyPI token is stored in GitHub. Before the first release:

1. Create a GitHub environment named `pypi` in the repository settings.
2. Add deployment protection or required reviewers to that environment.
3. In the PyPI account's **Publishing** settings, create a pending trusted
   publisher with these exact values:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `pyground-repl` |
   | GitHub owner | `siliconlad` |
   | Repository | `pyground` |
   | Workflow | `release.yml` |
   | Environment | `pypi` |

The first successful publish will create the `pyground-repl` project on PyPI.

## Publish a version

Update and validate the version on a branch:

```bash
uv version 0.2.0
uv lock --check
uv run pytest
```

Commit the version change and merge it into `main`. Then publish it manually:

1. Open the repository's **Actions** tab on GitHub.
2. Select **Release to PyPI**.
3. Choose **Run workflow**.
4. Select the `main` branch and enter the version, such as `0.2.0`.
5. Confirm **Run workflow** and approve the `pypi` environment if prompted.

The release workflow tests the project, builds and smoke-tests the wheel and
source distribution, waits for approval from the `pypi` environment if
configured, and publishes with PyPI Trusted Publishing.
