# Third-Party Notices

Grinta is distributed under the MIT license and includes dependencies from third-party
projects under their respective licenses.

## Source of Truth

- Direct dependencies are declared in `pyproject.toml`.
- Resolved and pinned dependency graph is recorded in `uv.lock`.

## Release Attribution Process

For each release candidate and final release:

1. Refresh lockfile and dependencies (`uv lock` / `uv sync`).
2. Generate a dependency license inventory using the active lockfile.
3. Review for copyleft or notice-carry obligations.
4. Publish/update the release artifact notice bundle if required by dependency licenses.

## Disclaimer

All third-party names, trademarks, and copyrights remain the property of their
respective owners. References in project documentation are for identification and
compatibility/comparison purposes only.
