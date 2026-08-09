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
| Template drift | Run `python3 tools/render_federation_templates.py --repo aguayluz-pr --repo-root /path/to/aguayluz-pr --check` from a local Hub checkout. |

### Coverage is a ratchet

`fail_under` records the coverage measured when the gate landed, minus a small
margin for variation across the CI Python matrix. Raise it as coverage improves.
**Never lower it to make a build pass** — that defeats the point of the gate.

### Generated files

Some files in this repo are rendered from templates in `thehub-pr` and must not
be hand-edited: the launchers (`PRII-*.command/.bat/.sh`, `Fix-Gatekeeper.command`),
the shared schema, `.github/dependabot.yml`, the CodeQL / secret-scan / pip-audit
workflows, `.pre-commit-config.yaml`, and the governance files including this one.
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
- Open the PR against `main` and fill out the PR template.
- By contributing you agree your work is licensed under the repository's
  [MIT License](LICENSE).

See also [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for community expectations.
