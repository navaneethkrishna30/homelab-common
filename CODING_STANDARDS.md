# Coding standards

Binding on every change, and what `code-review` checks against. This repo is the source for every service's standards; the
sections live in `template/_standards/`, and services get them stamped into their own `CODING_STANDARDS.md`.

- Every repo: [template/_standards/general.md](template/_standards/general.md)
- This repo (Python): [template/_standards/python.md](template/_standards/python.md)
  Exception to its no-raw-SQL rule: `platform/sql-tool`, whose job is running SQL it is given.
- Frontends: [template/_standards/typescript.md](template/_standards/typescript.md) with
  `tsconfig.strict.json` and `oxlintrc.json` beside it; frontend repos copy them.
- Process rules (branches, where work runs, finishing): Cortex `docs/skills/repo-hygiene`.
