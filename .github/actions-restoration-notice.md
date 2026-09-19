# GitHub Actions Restoration Notice

**Date:** 2026-09-19  
**Status:** RESTORED

## Summary

GitHub Actions runners were unavailable from approximately 2026-09-06 through
2026-09-19. Workflows triggered during that window completed as `failure`
immediately with `runner_id: 0`, `steps: []`, and no usable logs.

## Affected window

See thehub-pr issues #255 and #256 for the federation certification branch
protection and runner blocker that this restoration unblocks.

## Required re-runs

- AguaYLuz validation / full tests
- HAF contract
- Federation Compatibility
- Federation Certification Evidence
- Spatial / security / platform checks

## Exit criteria

Close this notice once at least one representative workflow on the current
`main` head allocates a real runner (`runner_id != 0`), executes its steps,
and publishes usable logs.
