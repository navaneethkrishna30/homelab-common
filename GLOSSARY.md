# Homelab platform

The words homelab-common and every service built on it share. Services keep their own `GLOSSARY.md` for their domain
and link here for platform terms; [SPEC.md](SPEC.md) holds how each one is built.

## Language

### Layers

**Platform**:
What every service runs on: Postgres, the gateway and the `sql` tool, deployed from this repo's `platform/` compose.

**Service**:
One deployable unit with its own repo, container, database schema, role and gateway prefix, named by a DNS label.
_Avoid_: app, unit (for a service)

**Library**:
The `homelab_common` Python package every service installs from a tag of this repo.

**Gateway**:
The single Caddy entry point that routes `/<name>/` to each service and is the only published port.
_Avoid_: Caddy (for the role)

**Machine**:
The host a set of services runs on (today only veronica), described by its own `veronica.yaml`.
_Avoid_: host (for the machine as a whole)

### Data

**Schema**:
The Postgres schema a service owns inside the shared `homelab` database, named after the service.

**Role**:
The Postgres login a service connects as; it owns the service's schema and may only append to and read the audit.

**Migration**:
A reviewed, forward-only change to a service's schema, applied by the migrate container.

**Migrate container**:
The one-shot container in a service's compose that brings its schema to the latest migration before the service starts.

### Calls and accountability

**Actor**:
Who a change is done for (`nav`, `jarvis`, `agent:<profile>`, `service:<name>`, `timer:<unit>`), carried unchanged
across service hops.
_Avoid_: caller (for the actor), user

**Caller**:
The service making a service-to-service call, as opposed to the actor it acts for.

**Audit**:
The one shared, append-only record of every write any service makes, kept in the same transaction as the write.
_Avoid_: activity, events (the per-service tables it replaces), audit log

**MCP tool**:
A service function exposed to Jarvis and agents over MCP, which is also a plain async function in the service.
_Avoid_: tool (alone, when the `sql` tool could be meant)

**`sql` tool**:
The platform's read-only MCP server that lets Jarvis query the database, mainly the audit.

**Background loop**:
A long-running task a service starts with itself (a schedule, a reaper), restarted if it fails.
_Avoid_: background job, job, timer

**Lease**:
Temporary exclusive use of a shared resource, granted and reclaimed by the `android` service, which owns all leases.

### Description and deploy

**service.yaml**:
The file at a service repo's root that declares what the platform needs to know about the service: name, network,
secret names, schema, gateway path, MCP exposure, telemetry and boot behaviour.
_Avoid_: spec (`ServiceSpec` is the code name of its schema)

**veronica.yaml**:
The only list of what runs on veronica: the platform tag and every service with the tag it runs.

**Generator**:
The homelab repo's tool that turns `veronica.yaml` and every `service.yaml` into committed gateway, environment,
MCP, boot-check and database files.

**Tag**:
A released version of a repo on `main`; the unit that deploy runs.
_Avoid_: release (for the deployed thing), version

**Deploy**:
Running `deploy.sh` so veronica runs exactly the tags `veronica.yaml` lists.
_Avoid_: ship

**Secrets**:
A repo's credentials, kept SOPS-encrypted in its committed `secrets.enc.env` and decrypted only at deploy.

**Boot-check**:
The machine's check after start-up that every service is running, healing the ones that are not.
_Avoid_: healthcheck (that is the container's own `/health` probe)

**Heal**:
Restarting a service boot-check finds down (`boot.heal` in `service.yaml`).

### Template

**Template**:
The copier project in `template/` that creates and updates service repos.

**Stamp**:
Creating a new service repo from the template.

**Managed file**:
A template file that `copier update` overwrites in every service, so it is changed only here.

**Repo-owned file**:
A template file created once by stamping and then owned by the service; `copier update` never touches it.

**`just check`**:
The single definition of "passes" for a repo, run by CI, builders and deploy alike.
_Avoid_: CI (for the checks themselves)
