# homelab-common

Shared base for Nav's homelab services: a Python library, a copier service template and the platform compose (Postgres, Caddy gateway, read-only sql tool, Langfuse).

The v1 design is in [SPEC.md](SPEC.md). Code rules for every agent: Cortex `docs/skills/repo-hygiene`.

## Develop

[AGENTS.md](AGENTS.md) has the layout and the commands; `uvx --from rust-just just check` must pass before a commit.
