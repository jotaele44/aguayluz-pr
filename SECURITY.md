<!-- Rendered from thehub-pr/federation-templates/baseline/SECURITY.md.
     Edit the template there and re-render (tools/render_federation_templates.py);
     do not hand-edit this file — template-drift.yml fails the build if you do. -->

# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue or PR for
a suspected vulnerability.

- Preferred: open a private [GitHub Security Advisory](https://github.com/jotaele44/aguayluz-pr/security/advisories/new)
  for this repository.
- Or email the maintainer: **jorge.gonzalez44@upr.edu** (subject line prefixed
  `[SECURITY]`).

Include enough detail to reproduce: affected file/version, impact, and a minimal
proof of concept if possible. We aim to acknowledge reports within a few days.

## Scope

This policy covers the `aguayluz-pr` source code and its CI/CD configuration.
The pipelines in this federation ingest **public records and public data feeds**;
please report concerns such as:

- credential/secret handling (env-var usage, accidental secret commits),
- code execution paths that run external commands or fetch remote data,
- dependency vulnerabilities not yet surfaced by the `pip-audit` workflow.

The public datasets these pipelines process are not themselves in scope; they are
governed by their originating sources.

Note that the HTTP backends in this federation bind to localhost and are CORS-
restricted to local origins. They are diagnostic tools, not internet-facing
services — but report it anyway if you find a path that changes that.

## Supported versions

These projects are pre-release; security fixes are applied to `main`.

## Automated tooling

Every repository in the federation runs the same baseline, single-sourced from
`thehub-pr/federation-templates/baseline/`:

- **Secret scanning** — `gitleaks` over full history, in CI
  (`.github/workflows/secret-scan.yml`) and in `pre-commit`.
- **Static analysis** — CodeQL for Python and TypeScript, per-PR and weekly
  (`.github/workflows/codeql.yml`).
- **Dependency auditing** — `pip-audit` against the locked dependency set, weekly
  (`.github/workflows/pip-audit.yml`).
- **Dependency updates** — Dependabot for pip, npm and GitHub Actions
  (`.github/dependabot.yml`).
- **Supply chain** — every GitHub Action is pinned to a commit SHA, and every
  workflow declares a least-privilege `permissions:` block.

The scanners that can produce first-run false positives (`gitleaks`, `pip-audit`)
are report-only today. Findings appear in the Actions log and the Security tab; a
green run means the scan executed, not that it found nothing.
