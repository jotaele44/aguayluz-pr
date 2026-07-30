<!-- Rendered from thehub-pr/federation-templates/baseline/pull_request_template.md.
     Edit the template there and re-render (tools/render_federation_templates.py);
     do not hand-edit this file — template-drift.yml fails the build if you do.

     Keep PRs small and single-purpose. Green CI is required to merge. -->

## Summary

<!-- What does this change do, and why? One to three bullets. -->

## Changes

-

## Quality gates

Tick what you ran locally. CI enforces these regardless — see CONTRIBUTING.md for
which jobs are blocking and which are report-only.

- [ ] `ruff check .` clean
- [ ] `python -m mypy` — no new findings
- [ ] `pytest -q` passes
- [ ] Coverage at or above the `fail_under` floor in `pyproject.toml`
- [ ] Lockfile regenerated if dependencies changed
- [ ] No rendered file hand-edited (template drift check passes)

## Scope & risk

- [ ] Single-purpose; no unrelated changes
- [ ] No runtime/behavior change, **or** the change is covered by tests
- [ ] Touches the federation contract (`schemas/`, `federation.json`)? If so,
      flag it — sibling repos consume these.

## End-to-end GUI capability parity

- [ ] No production, setup, analysis, or operator capability was added or changed,
      **or** `.federation/gui-capabilities.json` was updated in this PR.
- [ ] Every human-facing backend/analysis capability is usable through a
      discoverable GUI workflow without a terminal, script, direct API call,
      developer tools, or hidden URL.
- [ ] Every interactive GUI control is connected to working production behavior
      or explicitly classified `client_only`; there are no dead controls,
      production mocks, or placeholder workflows.
- [ ] Analytical/background results expose applicable progress, freshness,
      provenance, errors, and artifact access in the GUI.
- [ ] End-to-end GUI tests were added or updated, and
      `python scripts/check_gui_parity.py` passes.
- [ ] Any `internal` or `staged` exception includes its rationale, owner,
      tracking reference, and expiry.

## Verification

<!-- How did you confirm this works? Commands run and their output. If you
     changed behavior, show the before and after. -->
