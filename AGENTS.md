# homelab-common: agent guide

- Repo card: Cortex `entities/homelab-common`. Map: [SPEC.md](SPEC.md) (v1, final; ask rather than invent).
- Code rules for every agent: Cortex `docs/skills/repo-hygiene` (read it; it is not copied here).
- Branches: `main` released and tagged, `dev` integration, work branches from `dev`.

## Layout
- `src/homelab_common/`: the library (`create_app`, `load_config`, `db`, `audit`, `tool`, CLI)
- `template/`: the copier service template
- `platform/`: the platform compose (`platform/compose.yaml`: Postgres, Caddy, `sql` tool)
- `tests/`: flat pytest suite
- Integration tests (`pytest -m integration`) need `HOMELAB_TEST_DATABASE_URL` and the SQL in `platform/sql/` applied:
  run them on fedora against a throwaway `postgres:17.12` (`docker --context fedora`, tunnel with `ssh -N -L`).

## Commands
`just` is not installed; run it as `uvx --from rust-just just <recipe>`.
- `check`: sync, lint, types, test, secrets-guard (what CI and builders run)
- `sync` / `lint` / `types` / `test` / `secrets-guard`: the parts
