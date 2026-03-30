# Grinta Rename Plan

## Goal

Rename the current App-branded product, distribution, CLI surface, filesystem conventions, and user-facing strings to `Grinta` with a clean cutover.

This plan assumes:

- no runtime compatibility aliases
- no fallback env var names
- no dual directory probing like `.app` and `.grinta`
- no deprecated wrappers such as `app` -> `grinta`
- one breaking release where the old name stops working

## Hard Rules

- The application recognizes only the new names after cutover.
- Migration help is allowed as docs or a one-shot external migration script, but not as permanent runtime compatibility code.
- Historical mentions of the previous brand are allowed only in release notes and migration documentation.
- Internal names should become generic when branding is unnecessary. This reduces the cost of any future rename.

## Target Naming Decisions

Decide these before editing code. Do not start the rename until these are frozen.

- Product name: `Grinta`
- Python distribution name: `grinta-ai`
- CLI command: `grinta`
- Single-file launcher: `grinta.py`
- Frontend package name: `grinta-frontend`
- Repository slug: `Grinta`
- GitHub org/repo URL: target final canonical URL before merge
- User app directory: `.grinta`
- User home data directory: choose one form only; recommendation is `~/.grinta`
- Environment prefix: `GRINTA_`
- Docs domain: `docs.grinta.*`
- App domain: `app.grinta.*`
- Status domain: `status.grinta.*`
- Support email/domain: `*@grinta.*`

## Naming Policy

Use this rule to keep the rename clean:

- Brand-bearing external surfaces use `Grinta`.
- Internal technical abstractions use generic names unless the brand is part of the user-facing contract.

Recommended examples:

- `AppConfig` -> `ServerConfig`
- `app_logger` -> `service_logger`
- `AppMCPConfig` -> `ServerMCPConfig` unless the class is intentionally user-facing
- `app_tool_ok` -> `tool_ok`
- `APP_*` -> `GRINTA_*`
- `.app/context.md` -> `.grinta/context.md`

If you instead rename every branded symbol to `Grinta*`, the cutover is still valid, but you keep brand coupling deep in the codebase.

## Repo-Specific Blast Radius

Highest-signal rename clusters:

- Packaging and identity:
  - `pyproject.toml`
  - `backend/__init__.py`
  - `frontend/package.json`
  - `app.py`
  - `README.md`
- Config and branded types:
  - `backend/core/config/app_config.py`
  - `backend/core/config/__init__.py`
  - `backend/core/constants.py`
  - `backend/core/app_paths.py`
- Filesystem and workspace state:
  - `backend/core/workspace_context.py`
  - `backend/core/workspace_resolution.py`
  - `backend/orchestration/file_state_tracker.py`
  - `backend/orchestration/blackboard.py`
- User-facing URLs and help text:
  - `backend/gateway/utils/error_formatter.py`
  - `backend/gateway/app.py`
  - `backend/core/constants.py`
- Docs, scripts, and workflows:
  - `README.md`
  - `docs/ARCHITECTURE.md`
  - `docs/USER_GUIDE.md`
  - `docs/DEVELOPER.md`
  - `.github/workflows/app-resolver.yml`
  - `START_HERE.ps1`
  - `start_here.sh`

## What Must Change

### 1. Product Branding

Replace current App-facing branding in:

- README, docs, badges, architecture diagrams, examples, screenshots, issue templates, workflow names
- frontend titles, labels, descriptions, browser tab title, socket status text, empty states
- backend user-visible strings, telemetry event labels where they are user-facing, operator console output

Representative files:

- `README.md`
- `docs/**`
- `frontend/**`
- `backend/gateway/app.py`
- `backend/gateway/utils/error_formatter.py`

### 2. Distribution and CLI

Replace the package identity surfaces in:

- `pyproject.toml`
  - `project.name = "app-ai"` -> `grinta-ai`
  - description, authors, repository URL
  - `scripts.app` -> `scripts.grinta`
- `backend/__init__.py`
  - `__package_name__`
  - warning text
- top-level launcher
  - rename `app.py` -> `grinta.py`

No alias means the old CLI must stop existing in the release where this lands.

### 3. Branded Python Modules and Types

Rename files, imports, and symbols that still carry the current App-facing brand in the Python surface.

High-priority examples:

- `backend/core/config/app_config.py`
- imports of `AppConfig`
- `DEFAULT_APP_MCP_CONFIG_CLS` in `backend/core/constants.py`
- logger field names like `app_logger`
- payload fields such as `app_tool_ok`

Recommendation:

- prefer generic internal names such as `ServerConfig`, `service_logger`, `tool_ok`
- use `Grinta*` only where the name is part of an external contract

### 4. Environment Variables

All `APP_*` names become `GRINTA_*`.

This is a breaking operator change. Do not support both.

Important clusters include:

- runtime and startup
- host/port and app root
- default agent and max iterations
- API base URLs and auth/session configuration
- test toggles and CI configuration

Representative files:

- `backend/core/app_paths.py`
- `backend/core/constants.py`
- `start_server.py`
- startup scripts and docs

### 5. Filesystem Conventions

Choose one target and use it everywhere. Recommendation: lower-case only.

- `.app` -> `.grinta`
- `~/.app` -> `~/.grinta`

This affects:

- project memory and changelog files
- local KB storage
- playbooks
- blackboard/state trackers
- app workspace persistence
- any reserved-dir checks

Representative files:

- `backend/core/workspace_context.py`
- `backend/core/workspace_resolution.py`
- `backend/orchestration/file_state_tracker.py`
- `backend/orchestration/blackboard.py`
- `backend/persistence/**`
- `backend/playbooks/**`

### 6. URLs, Domains, Emails, and External References

Replace all hard-coded contact identities and external references in code and docs.

Representative surfaces may include:

- docs URLs
- status URLs
- product URLs
- container and download hostnames
- support email addresses

Representative files:

- `backend/core/constants.py`
- `backend/gateway/utils/error_formatter.py`
- docs and workflow files

### 7. Frontend and Socket/API Client Surfaces

Rename:

- package metadata in `frontend/package.json`
- browser titles and display strings
- any socket client labels or branded telemetry strings
- examples and onboarding text

If a reusable client package is still branded, rename it as part of the same release.

### 8. CI/CD, Workflows, Containers, and Infra Names

Rename:

- workflow filenames and workflow display names
- image tags and registries
- deployment hostnames
- example environment files
- devcontainer names
- support bot or mention handles if any

No alias means deployment config must switch atomically.

## Clean Cutover Strategy

Because you do not want compatibility shims, the safest plan is a staged implementation on a branch and a single release cutover.

### Phase 0. Freeze Decisions

Before code edits:

- freeze all final names listed above
- reserve domains, package names, repo slug, and container/image names
- decide whether internal branded symbols become `Grinta*` or generic names
- choose one data directory spelling only: recommended `.grinta`

### Phase 1. Internal Neutralization First

Reduce future rename cost before the public rename lands.

- rename internal symbols from App-branded names to generic names where possible
- rename fields like `app_tool_ok` to neutral names
- keep behavior unchanged
- avoid touching user-facing strings yet

This phase lowers the number of brand-bearing code symbols that must change during the final cut.

### Phase 2. Package and CLI Cutover

In one branch:

- rename `app.py` to `grinta.py`
- change console scripts in `pyproject.toml`
- rename distribution metadata and repository URLs
- update any install docs to use only `grinta`

Do not leave the old CLI as a secondary entry point.

### Phase 3. Config and Filesystem Cutover

Apply the breaking config/storage rename in one shot:

- `APP_*` -> `GRINTA_*`
- `.app` -> `.grinta`
- `~/.app` -> `~/.grinta`
- reserved-dir logic updated to only recognize new paths

Because there are no runtime fallbacks, publish a one-time migration script outside the app runtime if needed. Example responsibilities:

- copy or move old directories
- rename env keys in `.env` files
- rewrite config templates

That script is a migration tool, not a compatibility layer.

### Phase 4. Product Branding Cutover

Replace all user-facing App strings with `Grinta`.

- README, docs, frontend copy, help URLs, errors, startup banners, screenshots, issue templates, workflows

### Phase 5. External Infra Cutover

Switch external systems in the same release window:

- domains and docs links
- repo URL references
- container registry/image names
- CI variables and deployment settings

### Phase 6. Hard Validation

Validation gates for merge:

- `mypy --no-incremental backend`
- targeted pytest for all touched clusters
- package build succeeds
- frontend build succeeds
- zero runtime references to legacy launcher/env/fs surfaces
- targeted grep checks on legacy tokens are clean outside approved migration notes

## Search Gates

Before merge, these searches should be clean except in migration notes:

- exact env-var patterns for the outgoing `APP_*` names you are replacing
- exact filesystem references to `.app` and `~/.app`
- direct launcher references such as `app.py` and `scripts.app`
- old docs/status/support hostnames that are being retired

Approved residual locations:

- changelog entry describing the rename
- migration guide explaining old -> new names

## Breaking Changes to Announce

This rename is a major-version change. Release notes should explicitly call out:

- CLI command changed from `app` to `grinta`
- distribution changed from `app-ai` to `grinta-ai`
- env vars changed from `APP_*` to `GRINTA_*`
- app directory changed from `.app` to `.grinta`
- docs, status, and app URLs changed
- old names are not recognized by the new release

## Recommended Deliverables

Ship these together:

- the rename branch
- a migration guide
- a one-shot migration script for local settings/data if needed
- updated install/startup docs
- a release note stating the cutover is intentionally non-compatible

## Recommendation

If you want the cleanest long-term result, do this as:

- user-facing brand: `Grinta`
- external package/CLI/env/fs names: `grinta` / `GRINTA_*` / `.grinta`
- internal abstractions: generic names where branding adds no value

That gives you a clean cut now without baking the new brand unnecessarily deep into every technical symbol.