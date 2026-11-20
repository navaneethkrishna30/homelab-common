# platform

`compose.yaml` is the platform stack (project `homelab-platform`); more services (Caddy, the `sql` tool, Langfuse)
join it in later steps.

- **postgres**: Postgres 17 on the host network, listening on `127.0.0.1:5432` and `172.29.0.1:5432`. Data lives in
  `~/.local/state/homelab-postgres`; set `HOMELAB_PG_DATA` to use another directory (test stacks). The superuser
  password is `POSTGRES_PASSWORD`, passed by deploy.sh with `docker compose --env-file /run/homelab/secrets/platform.env`
  (decrypted from `secrets.enc.env`); the same file carries `DATABASE_PASSWORD`, the password of the `jarvis_ro` role.
- **SQL** (`sql/`): mounted into `docker-entrypoint-initdb.d`, so Postgres runs it once on an empty data directory.
  Every file is idempotent because deploy applies the same files again on each run: `00-databases.sql` creates the
  `langfuse` database, `10-common.sql` creates the `common` schema, `common.audit` and the read-only role `jarvis_ro`.
  Per-service roles and schemas are generated per service by the homelab repo, not written here.
- **caddy**: the gateway, `caddy:2.11`, on the `homelab` bridge with the platform's only published port
  `127.0.0.1:8480`. It reads `/etc/caddy` from `~/homelab/caddy` (set `HOMELAB_DIR` to use another directory): the
  hand-written `Caddyfile` there imports the generated `sites.d/<name>.caddy`, one per service. The healthcheck
  fetches `/health` with the image's busybox `wget`.
- Needs the external Docker network `homelab` (172.29.0.0/24, gateway 172.29.0.1) to exist before the stack starts.
- **sql** (`sql-tool/`): the read-only SQL MCP tool, built from this repo's library, connected as `jarvis_ro` (only
  `common.audit` is readable): one statement per call, 10 s timeout, 200 rows. Published through Caddy at `/sql/mcp`.

## After a power cut or an OOM kill
Everything has `restart: always`, so Docker brings it back by itself; tested with `kill -9` of each process and of all
of them at once. What makes that safe:
- **Postgres** replays its WAL (committed data survives). Its entrypoint waits up to 120 s for the bridge address
  `172.29.0.1` before starting, because Postgres otherwise only warns about a missing listen address and serves
  loopback only; its health check needs both addresses. `oom_score_adj: -500` makes the kernel kill apps first.
- **Services** may start before Postgres: `/health` stays 200, `/ready` is 503 until the database answers (connections
  are checked before use), and no restart is needed. Memory is capped (`mem_limit`), so a leak is OOM-killed inside
  its own cgroup and restarted.
- **Caddy** may need up to 30 s after a service restarts to notice it again (its health probe interval): `/ready` can
  answer 503 until then.
- The decrypted secrets in `/run/homelab/secrets` are gone after a reboot; running containers keep their environment, so
  nothing needs them until the next deploy (`./deploy.sh secrets` first).
- A container that is `unhealthy` but running is not restarted by Docker; boot-check reports it (the `ServiceDown` alert).
