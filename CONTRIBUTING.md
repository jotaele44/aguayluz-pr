<!-- Rendered from thehub-pr/federation-templates/baseline/CONTRIBUTING.md.
     Edit the template there and re-render (tools/render_federation_templates.py);
     do not hand-edit this file — template-drift.yml fails the build if you do. -->

# Contributing to aguayluz-pr

Thanks for helping improve `aguayluz-pr` — the Puerto Rico water, power and utility infrastructure intelligence producer in the Puerto Rico
Integrated Intelligence (PRII) federation.

This guide is shared across the federation, because the quality gates are the
same everywhere. Anything specific to this repo lives in its `README.md` and
`docs/`.

## Operating model

- Branch from the latest `main`; never commit directly to `main`.
- Keep PRs small and single-purpose. Fill out the PR template.
- Green CI is required to merge.
- These repos are siblings. Several checks clone `thehub-pr` next to the repo
  under test, so if you work locally across repos, keep them checked out in the
  same parent directory.

## Quick start

```bash
python -m pip install uv
uv pip install --system -e ".[dev]"   # or: -r requirements-dev.txt, per repo
pre-commit install                    # recommended — catches lint before push
```

## Quality gates

Run these locally before pushing. **CI is the authority** — each gate below maps
to a job under `.github/workflows/`, and whether a given job is blocking or
report-only is stated in a comment on the job itself. A few gates are
deliberately report-only while a backlog is worked down; that is recorded in the
job and in `pyproject.toml`, not hidden.

| Gate | Command |
|------|---------|
| Lint | `ruff check .` |
| Types | `python -m mypy` |
| Tests | `pytest -q` |
| Coverage | `pytest -q --cov` — must stay at or above the `fail_under` floor in `pyproject.toml` |
| Lockfile | `uv lock --check` |
| Docs sync | `python3 tools/check_docs_sync.py --base origin/main` |
| Template drift | Run `python3 tools/render_federation_templates.py --repo aguayluz-pr --repo-root /path/to/aguayluz-pr --check` from a local Hub checkout. |

### Coverage is a ratchet

`fail_under` records the coverage measured when the gate landed, minus a small
margin for variation across the CI Python matrix. Raise it as coverage improves.
**Never lower it to make a build pass** — that defeats the point of the gate.

### Documentation stays true

A document that describes this repo must not contradict it. If your change makes one
untrue, update that document in the same change. This is enforced: the `docs-sync` CI
job, the `docs-sync` pre-commit hook and a Claude Code Stop hook all run
`tools/check_docs_sync.py`, which checks three things.

1. **Co-change.** `.federation/docs-sync.json` declares which docs cover which paths.
   Changing a covered path without touching its doc fails, unless a commit message or
   the PR description carries `Docs-Impact: none - <reason>` (say why no doc needs to
   change; ten characters minimum, and reviewers will read it).
2. **References.** A change may not leave a doc pointing at a path that no longer
   exists. Only references *your change* broke count; older ones are not yours to fix
   here. A deliberate reference (a generated file, say) goes in `ignore_refs`, or is
   waived for that one doc with `Docs-Impact: <doc> - <reason>`.
3. **The manifest itself** must stay valid, and its globs must still match something.

Snapshots (dated audits, receipts, ADRs, changelogs) describe a moment rather than the
repo, so they are listed under `exempt_docs` and never forced to change. Setting
`"mode": "report"` in the manifest prints the same findings without failing the job;
use it only while triaging a new manifest. A failing job blocks a merge only once
`docs-sync` is a required status check for `main`, which is a repository setting.

### Generated files

Some files in this repo are rendered from templates in `thehub-pr` and must not
be hand-edited: the launchers (`PRII-*.command/.bat/.sh`, `Fix-Gatekeeper.command`),
the shared schema, `.github/dependabot.yml`, the CodeQL / secret-scan / pip-audit /
docs-sync workflows, `tools/check_docs_sync.py`, `.claude/settings.json`, `CLAUDE.md`,
`.pre-commit-config.yaml`, and the governance files including this one.
Each carries a header saying so. Edit the template in
`thehub-pr/federation-templates/baseline/`, re-render, and commit both repos —
`template-drift.yml` fails the build if a rendered file diverges.

## Dependencies

Dependencies are pinned so builds are reproducible. When you change one, update
the lockfile with the command in the table above and commit it alongside your
change. Dependabot proposes updates weekly for pip, npm and GitHub Actions.

## Security

Do not open a public issue for a suspected vulnerability — see
[`SECURITY.md`](SECURITY.md) for the private reporting path. Secret scanning runs
in `pre-commit` and in CI, but it is a backstop, not a substitute for keeping
credentials in environment variables and out of commits.

## Commit & PR

- Write clear, imperative commit messages that explain the *why*.
- Open the PR against `main` and fill out the template.
- By contributing you agree your work is licensed under the repository's
  [MIT License](LICENSE).

See also [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations.
