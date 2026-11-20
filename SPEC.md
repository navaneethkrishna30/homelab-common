# homelab-common v1: specification

Status: approved decisions, written 2026-11-20 by Claude from the wayfinder map "1. homelab-common"
(Hermes kanban board `homelab-services`, card `t_4d7363a2`). Every decision below was made with Nav; the
resolution comments on the archived tickets hold the reasoning. Builders follow this file and Cortex
`docs/skills/repo-hygiene`; where this file is silent, ask, don't invent. Section 14 lists what is still open.

Design context (why services at all): Claude Doc "Homelab services: design",
https://claude.ai/artifact/QS4FYUGnJE3Pjp5nwq3Pym (not readable by agents; this spec is self-contained).

## 1. Purpose and scope

`homelab-common` is the base every homelab service is built on:

- a **Python library** (`homelab_common`) every service installs;
- a **copier template** that creates a new service repo;
- the **platform compose**: Postgres, the Caddy gateway, the read-only `sql` MCP tool, Langfuse.

v1 is done when a service stamped from the template runs end to end on veronica: deployed by `deploy.sh` from
a tag, migrated, reachable at `https://svc.fin-alkaline.ts.net/<name>/` (REST) and `/<name>/mcp` (MCP),
auditing its writes, and visible in Grafana (traces, metrics, logs). The first real service is `tasks`.

Not in v1 (built with the service that first needs it): approvals (`homeassistant`), leases (`android`), the
notify client (`devices`). Also out: audit pruning policy and backups of the platform database (machine level,
later), the hub Activity page, per-service designs.

## 2. Repos and layers

| Layer | Repo | Holds |
|---|---|---|
| Machine | `homelab` (existing, private) | host setup and units, third-party stacks (Home Assistant, Mosquitto, Immich, SearXNG, browser, telemetry submodule), `veronica.yaml`, `deploy.sh`, the generator (`tools/generate/`) |
| Platform | `homelab-common` (this repo, **public**) | library, template, platform compose; no secrets except its own `secrets.enc.env` ciphertext |
| Services | one repo each (private allowed) | one service; created from the template |
| Separate | Cortex | unchanged: own repo, own Postgres, own deploy |

- Language: Python + FastAPI by default; another language only where its tooling is clearly better for that
  service (decided per service).
- Services install the library from a git tag: `[tool.uv.sources] homelab-common = { git = "https://github.com/navaneethkrishna30/homelab-common", tag = "vX.Y.Z" }`.
- The template's version is the same tag as the library.

## 3. Network and platform

- **One Docker bridge network `homelab`**, external, subnet `172.29.0.0/24`, gateway `172.29.0.1`.
- **Postgres 17 runs on the host network**, data `~/.local/state/homelab-postgres`, listening on
  `127.0.0.1:5432` and `172.29.0.1:5432`. Containers reach it at `172.29.0.1:5432`, never `127.0.0.1`.
- Databases: `homelab` (one schema per service, each owned by that service's role) and `langfuse` (Langfuse
  uses `public` and migrates itself).
- Roles: one per service (owns its schema; `INSERT` + `SELECT` on `common.audit`, nothing else outside its
  schema); `jarvis_ro`, read-only, in v1 allowed `SELECT` on `common.audit` only. The platform's init SQL
  creates roles, schemas and `common`; the generator emits role/schema lines per service.
- **Every service listens on `8000` inside its container and publishes nothing.** Exceptions that need the
  host network (only `android`, for adb) declare `run.network: host` in `service.yaml`.
- **Caddy** is the only published port: `127.0.0.1:8480`, on the `homelab` bridge, published to the tailnet
  as the Tailscale Service `svc` (`tailscale serve --service=svc:svc --https=443 127.0.0.1:8480`, Service
  defined once in the admin console). Global options: `servers { trusted_proxies static 172.29.0.1 }` (through the published port Caddy sees
  the bridge gateway as the peer, not 127.0.0.1; decided with Nav 2026-11-20 after testing).
  One file per service, generated (section 6). Existing `svc:<app>` serve entries stay until each app moves.
- **Hermes** (on the host) reaches services through Caddy's loopback bind, `http://127.0.0.1:8480/<name>/mcp`. The
  host of a Tailscale Service cannot resolve or reach the Service names it hosts (tested 2026-11-20), and a tagged
  host carries no `Tailscale-User-*` headers anyway; the actor comes from `X-Homelab-Actor`. Other tailnet devices
  use `https://svc.fin-alkaline.ts.net/<name>/`.
- **Service to service:** directly over the bridge, `http://<name>:8000`; the library adds the caller header
  and `traceparent`.
- **Alloy** (telemetry repo) joins the `homelab` bridge; services send OTLP to `http://alloy:4318`. No scrape
  config is generated.
- **`sql` tool:** a small MCP server in the platform compose, connected as `jarvis_ro`: one statement per
  call, statement timeout 10 s, row cap 200. Published through Caddy like a service.
- **Langfuse v3** in the platform compose (compose profile `observability`, stoppable alone): web, worker,
  ClickHouse, Valkey, MinIO; no bundled Postgres, `DATABASE_URL` points at `172.29.0.1:5432/langfuse`.
  Measured idle cost: about 0.45 GiB for the infra containers, budget 2 to 3 GiB for the whole stack.
  Hermes gets the official `langfuse` plugin (`HERMES_LANGFUSE_PUBLIC_KEY`, `HERMES_LANGFUSE_SECRET_KEY`,
  `HERMES_LANGFUSE_BASE_URL` = the Caddy route), beside the existing `jarvis-telemetry` plugin until Langfuse
  is proven to cover it. Research: card `t_259d706b`, finding posted on `t_4d7363a2`.

## 4. Library v1 public API

Five names. Everything else is automatic.

```python
from homelab_common import create_app, load_config, db, audit, tool

class Settings(CommonSettings):          # pydantic-settings; env > config/config.yaml
    reminder_lead: int = 15

cfg: Settings = load_config(Settings)    # fails at boot on a typo or missing value
app: FastAPI = create_app("tasks", cfg, routers=[tasks_router], tools=[list_tasks, add_task])

@tool                                    # an MCP tool; also a plain async function
async def add_task(title: str, due: date | None = None) -> TaskOut:
    async with db.session() as s:        # SQLAlchemy 2.0 AsyncSession; search_path = the service schema
        task = Task(title=title, due=due)
        s.add(task)
        await s.flush()
        await audit.record(s, action="task.add", target=("task", str(task.id)),
                           after=audit.changes(None, task), summary=f"Added {title}")
        return TaskOut.model_validate(task)
```

| Module | v1 contents |
|---|---|
| `create_app` | FastAPI app with `/health` (process up) and `/ready` (database reachable, migrations current), JSON logging, OpenTelemetry (section 8), caller/device/trace middleware, FastMCP mounted at `/mcp` beside REST, the given routers and tools |
| `load_config` | pydantic-settings model from `config/config.yaml` + environment, `extra="forbid"` |
| `db` | async SQLAlchemy 2.0 engine and session factory (asyncpg), pool sized from settings, schema = service name |
| `audit` | `record(...)`, `changes(before, after)`, the `AuditEvent` model (section 7) |
| `tool` | decorator registering an async function as an MCP tool; instruments it (section 8) |
| `CommonSettings` | database URL parts, OTLP endpoint, service name, public path, from the generated env fragment |
| CLI | `homelab-common validate service.yaml` (used by `just check` and CI) |

- **MCP:** FastMCP 4.x (PrefectHQ), mounted with `mcp.http_app(path="/")` and the app's lifespan combined.
  `get_http_headers()` strips `authorization` by default; read identity headers explicitly. Research: `t_98b2b84f`.
- **Database:** SQLAlchemy 2.0 async ORM; API and MCP payloads are separate Pydantic models, never ORM objects.
- **Migrations:** Alembic, autogenerated from the models, reviewed, **forward only** (no `downgrade` is ever
  run), version table in the service's schema, run by the one-shot `migrate` container.
- **Headers in:** `X-Homelab-Actor` (the audit actor, forwarded unchanged on service-to-service calls; without it a
  `Tailscale-User-Login` means `nav`, neither means `unknown`; Hermes MCP entries send `jarvis` or `agent:<profile>` as a
  static header; decided with Nav 2026-11-20), `Tailscale-User-Login` (person), `X-Homelab-Device` (device id, when sent), `X-Hermes-Turn`
  and `traceparent` (optional; absent today), caller header on service-to-service calls. All optional; missing
  means NULL, never an error.

## 5. `service.yaml`

At the root of every service repo. Parsed by a pydantic model in the library (`extra="forbid"`); a field
exists only if something reads it.

```yaml
apiVersion: homelab/v1
name: tasks                       # DNS label: container, Caddy prefix, schema, role, MCP server key
title: Tasks
description: Boards, reminders and the tasks API
repo: navaneethkrishna30/tasks
run:
  port: 8000                      # default 8000
  network: homelab                # homelab | host (host must say why in a comment)
  env: [TASKS_TOKEN]              # secret NAMES only; values live in secrets.enc.env
database: {schema: tasks}         # omit for a service without a database
gateway: {path: /tasks}           # default /<name>
mcp:
  enabled: true                   # default false
  path: /mcp
  profiles: [builder]             # specialist Hermes profiles that also get it; Jarvis (default) always does
  tools: ["tasks_*"]              # globs narrowing the tools exposed; default all
telemetry: {otlp: true}
boot: {heal: true, units: []}     # boot-check: restart if down; extra host units to watch
```

No `backup` field (backups are decided later, at machine level). No image, build, limits, app config,
secrets or Postgres host: compose, `config.yaml` and the platform own those.

## 6. `veronica.yaml` and the generator

`~/homelab/veronica.yaml` is the only list of what runs on veronica:

```yaml
apiVersion: homelab/v1
machine: veronica
network: {name: homelab, subnet: 172.29.0.0/24, gateway: 172.29.0.1}
postgres: {host: 172.29.0.1, port: 5432, version: 17, data: /home/veronica/.local/state/homelab-postgres}
gateway: {caddy: {bind: 127.0.0.1:8480}, tailscale: svc:svc}
platform: {repo: navaneethkrishna30/homelab-common, tag: v0.1.0, compose: platform/compose.yaml}
services:
  - {name: tasks, repo: navaneethkrishna30/tasks, tag: v0.1.0, order: 20}
stacks:                           # third-party compose dirs in the homelab repo, as today
  - {name: homeassistant, path: homeassistant, order: 5}
```

- The **tag is the deploy unit**. Changing a service means releasing a tag on its `main` and bumping it here.
- Checkouts live at `/home/apps/srv/<name>`, detached at the tag, disposable (`clean -ffdx` on every sync).
- **Generator:** `~/homelab/tools/generate/` (own `pyproject.toml`, imports the schema from the pinned
  library). It reads `veronica.yaml` and every checked-out `service.yaml` and writes **committed** files in the
  homelab repo, each stamped `# generated from service.yaml, do not edit`:

| Output | Read by |
|---|---|
| `caddy/sites.d/<name>.caddy` (hand-written `caddy/Caddyfile` imports them) | Caddy |
| `generated/env/<name>.env` (public path/URL, `OTEL_*`, database host/port/schema) | the service's compose, first `env_file` |
| `jarvis/generated/mcp.sh` + `mcp-grants.json` | `jarvis/apply.sh` (`hermes config set`) and `apply-profiles.sh` |
| `boot-check/services.toml` | boot-check |
| `generated/databases.sql` (roles, schemas, grants) | the platform init step |

Caddy site file shape (per service):

```caddyfile
redir /tasks /tasks/ 308
handle_path /tasks/* {
	reverse_proxy tasks:8000 {
		header_up X-Forwarded-Prefix /tasks
		header_up X-Tailscale-User-Login {http.request.header.Tailscale-User-Login}
		health_uri /health
	}
}
```

Hermes MCP entries per service, default profile: `mcp_servers.<name>.url
http://127.0.0.1:8480/<name>/mcp`, `connect_timeout 30`, `tools.include` from `mcp.tools`;
profiles in `mcp.profiles` get the same server. Written only through `hermes config set` (never text-patched);
applied without a gateway restart. Research: `t_854af8b7`.

- Runs as `veronica`, first step of `deploy.sh`, writes atomically. **Never** at runtime, from a timer or by a
  service. `generate --check` regenerates into a temp dir and diffs against git; deploy fails on a diff.

## 7. Audit

One shared, append-only table `common.audit` in the `homelab` database, written by the library **in the same
transaction** as the change. Replaces per-service activity tables (`tasks`' `events` table goes when it moves).

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity | |
| `at` | timestamptz, default now() | indexed |
| `service` | text(40) | the writer |
| `action` | text(80) | `resource.verb`: `task.move`, `ha.service.call`, `emulator.start` |
| `actor` | text(40) | origin: `nav`, `jarvis`, `service:<name>`, `timer:<unit>`, `agent:<profile>`; forwarded unchanged across service hops |
| `actor_detail` | jsonb | Hermes profile, model, client app/version |
| `device` | text(64) | `X-Homelab-Device`, else NULL |
| `source_ip` | inet | from serve's `X-Forwarded-For` via Caddy |
| `turn_id` | text(64) | `X-Hermes-Turn`, NULL until Hermes sends it |
| `trace_id`, `span_id` | text(32), text(16) | current span |
| `target_kind`, `target_id` | text(40), text(120) | no foreign keys |
| `before`, `after` | jsonb | **changed fields only**, secrets masked (`password|token|secret|key|code|pin` → `***`), 8 KiB cap each |
| `result` | text(12) | `ok` / `denied` / `failed` / `pending` (check constraint) |
| `error` | text(500) | class + message, no traceback |
| `summary` | text(200) | the human line |
| `extra` | jsonb | `call_id`, `job_id`, later `approval_id` |

- Indexes: `(at)`, `(actor, at)`, `(target_kind, target_id, at)`.
- External side effects (Home Assistant, adb, MQTT) write a `pending` row, then an outcome row joined by
  `extra.call_id`. Denied actions are audited; reads are not.
- Retention: at least the last 30 days stay in the database; older rows go to the backups. Pruning policy is
  decided later with the machine-level backups (nothing prunes in v1).
- Jarvis reads it through the `sql` tool; its skill carries example queries. A hub Activity page is later work.

## 8. Observability

The library instruments everything through the OpenTelemetry SDK, exporting traces, metrics and logs over
OTLP to Alloy (`http://alloy:4318`), every 15 s for metrics. No `/metrics` endpoint, no scrape.

- **Names:** OpenTelemetry semantic conventions verbatim, including the HTTP, database, MCP and GenAI ones:
  `http.server.request.duration`, `http.client.request.duration`, `db.client.operation.duration`,
  `db.client.connection.count`, `mcp.server.operation.duration`, `process.cpu.time`, `process.memory.usage`.
  Units in metadata (UCUM `s`, `By`), never in names. A service's own metrics: `homelab.<subject>.<measure>`
  (e.g. `homelab.emulator.start.duration` → Prometheus `homelab_emulator_start_duration_seconds`).
- **Histogram buckets (seconds):** HTTP `[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5,
  7.5, 10]`; DB `[0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]`; MCP `[0.01, 0.02,
  0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]`.
- **Errors:** `error.type` (plus status code) on the duration histograms; rates computed in PromQL. No
  `*_errors_total` counters.
- **MCP tools** are instrumented by the library's `@tool` wrapper (not FastMCP's telemetry): span
  `tools/call <tool>` with `mcp.method.name`, `gen_ai.tool.name`, `gen_ai.operation.name=execute_tool`, and
  the duration histogram, identical in shape to REST routes.
- **Spans:** route `GET /tasks/{task_id}` (template, never the raw path), client `GET`, DB
  `SELECT tasks`. On the Hermes side the `jarvis-telemetry` plugin aligns to `invoke_agent` / `chat` spans with
  `gen_ai.request.model`, `gen_ai.usage.*`, `gen_ai.conversation.id`.
- **One trace per Jarvis turn**; services join it through `traceparent` when Hermes sends it.
- **Cardinality:** metric labels only from an allowlist (route templates, tool names, methods, status codes,
  `error.type`). Ids (task, turn, device), paths and SQL text go on spans and logs only. `/health` and `/ready`
  are not instrumented. 100% of traces kept.
- **Logs:** JSON to stdout and OTLP to Loki; keys are the OTel attribute names (`http.route`,
  `gen_ai.tool.name`, `trace_id`).
- **Health:** `/health` and `/ready` on every service, Docker `HEALTHCHECK` on every container.
- **Alloy changes** (telemetry repo, one card): join the `homelab` bridge; export only three resource labels
  (`service_name`, `host_name`, `deployment_environment`) instead of `resource_to_telemetry_conversion`;
  `include_scope_labels = false`. **Before changing, verify every existing Grafana dashboard and alert**
  (Claude Code, Jarvis, machines) still works.
- Dashboards are later work.

## 9. The service template

`copier copy --trust gh:navaneethkrishna30/homelab-common <dir>` (template at `template/`). Output:

```
<name>/
├── .copier-answers.yml       ├── service.yaml
├── .github/workflows/ci.yml  ├── pyproject.toml, uv.lock, .python-version (3.14)
├── .sops.yaml                ├── justfile
├── .gitignore (*.env, !*.enc.env), .dockerignore
├── secrets.enc.env           ├── config/config.yaml
├── Dockerfile                ├── src/<name>/ (app.py, settings.py, models.py, api.py, tools.py)
├── compose.yaml              ├── migrations/ (Alembic async env.py, versions/)
├── alembic.ini               ├── tests/ (conftest.py)
├── README.md                 └── AGENTS.md
```

- **Python 3.14 + uv** (pinned in the image), `uv.lock` committed, installs `--locked`.
- **Dockerfile:** single stage on `ghcr.io/astral-sh/uv:<pinned>-python3.14-trixie-slim`, dependency layer
  first, runs as uid 1000, `HEALTHCHECK` on `/health` using Python's stdlib (no curl).
- **compose.yaml:** `api` and a one-shot `migrate` (`profiles: [tools]`, runs `alembic upgrade head`),
  network `homelab` (external), no `ports:`, `read_only: true`, `tmpfs: /tmp`, `env_file` = the generated
  fragment then `/run/homelab/secrets/<name>.env`.
- **config/config.yaml:** tunables only, no secrets, no URLs or ports; environment overrides YAML.
- **Typing (Nav):** every function has typed parameters and a return type, no `Any`, no unknown or untyped
  values; anything crossing a module or service boundary is a Pydantic model. Enforced by **pyright strict**
  and ruff's `ANN` rules (including `ANN401`). Silencing them (`type: ignore`, `cast`) is not allowed.
- **Lint/format:** ruff only (`check` + `format --check`), line length 100, target py314.
- **Tests:** one flat `tests/`, pytest + pytest-asyncio + httpx `ASGITransport`; per repo-hygiene (logic that
  decides or parses, one case per outcome, no coverage gate, no snapshots).
- **`just check`** is the single definition of "passes": `uv sync --locked`, ruff, pyright, pytest,
  `homelab-common validate service.yaml`, and a guard that every `*.enc.env` is SOPS-encrypted.
- **CI:** GitHub Actions running `just check` on pushes and pull requests to `dev` and `main` only. If private
  repos exceed the free 2,000 minutes a month, add a self-hosted runner. `just check` also runs in builders
  before they complete a card and in `deploy.sh` before it deploys a tag.
- **Branches:** `main` (released, tagged), `dev` (integration), work branches from `dev`. A release merges
  `dev` into `main` and tags `main`; `dev` then catches up with `main`. Deploys use tags on `main` only.
- **AGENTS.md** links Cortex `docs/skills/repo-hygiene` (never copies it), names the repo's Cortex card and
  map, lists the commands.
- **Two tiers:** managed files are overwritten by `copier update` (Dockerfile, compose.yaml, CI, alembic.ini,
  `migrations/env.py`, `.sops.yaml`, `.gitignore`, `.dockerignore`, justfile); repo-owned files are created once
  (`_skip_if_exists`: `service.yaml`, `config/config.yaml`, README, AGENTS.md, `src/**`, `tests/test_*.py`,
  `migrations/versions/**`). Template updates run in throwaway clones, one PR per repo, never on
  `/home/apps/srv` checkouts.

## 10. Secrets

- **SOPS + age**, dotenv format, one `secrets.enc.env` per deployable unit (each service, the platform, later
  the backup tool and third-party stacks), committed. The `.enc.env` suffix is required (SOPS picks the dotenv
  store from it).
- The **age private key** is `~/.config/sops/age/keys.txt` on veronica (0600, owner `veronica`, never root).
  Each repo's `.sops.yaml` holds the public key. The key file is included in the restic backups.
- **Adding a value:** `sops set` for generated values (Claude does this and commits), `sops edit` for real
  credentials. `sops unset` to remove. `veronica.yaml` and `service.yaml` carry names only.
- **Deploy decrypts as `veronica`** to `/run/homelab/secrets/<name>.env` (tmpfs, gone on reboot; containers keep
  their stored config) for new services, and to the existing paths for existing stacks. Values are never
  printed.
- `~/homelab/secrets.sh` retires in one migration commit; `secrets.tar.gpg` is deleted only after a successful
  restore drill.
- **Rotation:** two passes of `sops updatekeys` (add the new recipient, re-encrypt everywhere, remove the old,
  re-encrypt), then swap the key file. A leaked key also means rotating the credentials themselves.

## 11. Deploy

`deploy.sh` sections, in this order, each runnable alone and idempotent:

| Section | Runs as | Does |
|---|---|---|
| `preflight` | root | docker up, `homelab` network exists (create it), `sops`/`age` installed, key readable, disk space |
| `units` | root | systemd units, as today |
| `sync` | veronica | per `veronica.yaml` entry: clone if missing, `fetch --tags --force`, `checkout --detach <tag>`, `clean -ffdx` |
| `generate` | veronica | `generate --check`; abort on any diff |
| `secrets` | veronica | decrypt every unit's `secrets.enc.env` to its consumer path; check every `run.env` name is present; refuse an unencrypted `*.enc.env` |
| `stacks` | veronica | platform first (Postgres, `pg_isready`, roles from `databases.sql`), then each unit in `order`: `just check` on the tag, `compose run --rm migrate`, `compose up -d --wait --wait-timeout 180 --remove-orphans`; then third-party stacks |
| `check` | veronica | `/ready` through Caddy (`127.0.0.1:8480/<name>/ready`, 2 s interval, 120 s cap) plus container health; print a table, write `~/.local/state/homelab-deploy/last.json`, exit 1 if anything is not ready |
| `serve` | root | `ts-services/serve.sh` |

- The root sections are Nav's (no passwordless sudo). The `veronica` sections let Claude and agents ship a
  tag without him.
- A failing section aborts before touching what comes after; old containers keep running.
- **No automatic rollback:** put the previous tag back in `veronica.yaml` and run `sync secrets stacks check`.

## 12. Recovery on a new machine

1. Install Fedora, user `veronica` (uid 1000), Docker + group, git, uv; `tailscale up` with `tag:server`.
2. Get the age key back: Nav's restic password (Proton Pass) → `restore-age-key.sh` restores
   `~/.config/sops/age/keys.txt` from the backup drive, or from B2 when the drive is gone (asks Nav for
   Backblaze credentials, which he can re-mint in the Backblaze console). Verify with one `sops -d`.
3. `git clone --recurse-submodules` the homelab repo.
4. `sudo ./deploy.sh preflight units`, then `./deploy.sh sync generate secrets stacks check`.
5. Restore data per `backup/RESTORE.md`, then `./deploy.sh stacks check` again.
6. `sudo ./deploy.sh serve`; confirm the `svc` Tailscale Service points at this host.
7. Verify: `check` table all ready, the hub loads, Prometheus has fresh series, a test alert reaches the phone.
8. Jarvis (Hermes user units) and Cortex (system unit) are outside `deploy.sh`: run `jarvis/apply.sh` and
   Cortex's own deploy.

## 13. Build order for v1

Each step is one or more cards for `builder`, reviewed by Claude, merged to `dev`, released by tag.

1. Repo skeleton: this repo's layout, `justfile`, CI, branches `main`/`dev`, AGENTS.md.
2. Library: `load_config`, `db`, `create_app` (health, ready, logging, middleware), `tool` + FastMCP mount,
   `audit`, OpenTelemetry; `validate` CLI; tests for the deciding logic only.
3. Platform compose: Postgres (host network, both listen addresses, init SQL with `common.audit` and roles),
   Caddy, `sql` tool.
4. Template (copier) and a throwaway `hello` service stamped from it.
5. Homelab repo: `veronica.yaml`, `tools/generate/`, the `deploy.sh` rework, SOPS adoption, `secrets.sh`
   retirement (after the restore drill), `restore-age-key.sh`.
6. Alloy changes (after the dashboard check).
7. End to end: deploy `hello` from a tag, reach it through `svc`, call its MCP tool from Hermes, see its audit
   row and its trace. Then delete `hello` and move to `tasks`.
8. Langfuse in the platform compose and the Hermes plugin (board card "2. Langfuse + Hermes plugin").

## 14. Open items

- Hermes does not send `X-Hermes-Turn` / `traceparent` on MCP calls. Card "Hermes: send X-Hermes-Turn and
  traceparent on MCP calls (upstream PR)"; services tolerate their absence.
- The device id format (`X-Homelab-Device`) is defined by the `devices` service; until then it is NULL.
- Audit pruning and platform-database backups: decided with machine-level backups.
- Whether `jarvis_ro` sees more than `common.audit`: decided per service as each moves.
- The `svc` Tailscale Service must be defined in the admin console by Nav before step 7.

## 15. Decisions made while building v1 (2026-11-20, Claude, Nav asleep and out of the loop; revisit freely)
- **Tool names** are the function names (`add_note`); Hermes prefixes the server. `mcp.tools` globs match those names.
- **MCP path:** the endpoint answers at exactly `/mcp` (no redirect: behind Caddy a redirect to `/mcp/` loses the
  service prefix). `CommonSettings.public_host` (default `svc.fin-alkaline.ts.net`) is the only host it accepts besides loopback.
- **Role passwords:** every service role gets the service's own `DATABASE_PASSWORD` secret; deploy applies
  `generated/databases.sql`, then `ALTER ROLE ... PASSWORD` from the decrypted secrets (psql quotes the value).
  `jarvis_ro` uses the platform's `DATABASE_PASSWORD`. The platform's secrets decrypt to `/run/homelab/secrets/platform.env`
  and reach compose through `--env-file`, so each container sees only what it needs (the `sql` tool never sees the superuser).
- **The `sql` tool** lives in `platform/sql-tool/` (library + one tool, runs as `jarvis_ro`); its `service.yaml` is read by
  the generator from the platform checkout, so it gets a Caddy site and an MCP entry like any service.
- **Labels:** the resource attributes are `service.name`, `host.name` (the machine, from `HOST_NAME`, set by the generated
  env) and `deployment.environment=homelab`; `service.instance.id` is `<service>@<host>` (stable: a random id makes a new
  Prometheus series set and Loki stream on every restart).
- **`veronica.yaml` has no `stacks` list:** nothing would read it; deploy.sh's `thirdparty` section keeps the existing
  third-party stacks as they were. `secrets.sh` is not retired (that waits for a SOPS restore drill).
- **Not built (no consumer yet):** the service-to-service HTTP client with the caller header and `traceparent`.
- **Crash safety** (power cut, OOM): see `platform/README.md`; tested with `kill -9` of every process.

