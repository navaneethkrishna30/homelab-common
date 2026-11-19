# platform

`compose.yaml` is the platform stack (project `homelab-platform`); more services (Caddy, the `sql` tool, Langfuse)
join it in later steps.

- **postgres**: Postgres 17 on the host network, listening on `127.0.0.1:5432` and `172.29.0.1:5432`. Data lives in
  `~/.local/state/homelab-postgres`; set `HOMELAB_PG_DATA` to use another directory (test stacks). The superuser
  password comes from `/run/homelab/secrets/platform.env` (`POSTGRES_PASSWORD`), decrypted by deploy.
- **SQL** (`sql/`): mounted into `docker-entrypoint-initdb.d`, so Postgres runs it once on an empty data directory.
  Every file is idempotent because deploy applies the same files again on each run: `00-databases.sql` creates the
  `langfuse` database, `10-common.sql` creates the `common` schema, `common.audit` and the read-only role `jarvis_ro`.
  Per-service roles and schemas are generated per service by the homelab repo, not written here.
- Needs the external Docker network `homelab` (172.29.0.0/24, gateway 172.29.0.1) to exist before the stack starts.
