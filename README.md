# homelab-common

Shared base for Nav's homelab services: a Python library, a copier service template and the platform compose (Postgres, Caddy gateway, read-only sql tool).

The v1 design is in [SPEC.md](SPEC.md). Code rules for every agent: Cortex `docs/skills/repo-hygiene`.

## Develop

[AGENTS.md](AGENTS.md) has the layout and the commands; `uvx --from rust-just just check` must pass before a commit.

## Use
- **New service:** `uvx copier copy --trust gh:navaneethkrishna30/homelab-common <dir>` (answers: name, title, description,
  the age public key, the library tag). It stamps the repo, locks it, and `uvx --from rust-just just check` passes
  straight away. Then add its secrets (`secrets.enc.env`, see the stamped README), give it a Cortex card, push, tag
  `main`, and add it to the homelab repo's `veronica.yaml`.
- **Update a service from the template:** `uvx copier update --trust` in a throwaway clone, one PR per repo.
- **Library only:** `homelab-common validate service.yaml`; the five names (`create_app`, `load_config`, `db`,
  `audit`, `tool`) are in SPEC section 4.

## Release (this repo)
Merge `dev` into `main`, tag `main` `vX.Y.Z`, push both, then `dev` catches up with `main`. The tag is the library
version, the template version and the platform compose version; the template's `library_tag` default and the
homelab repo's `veronica.yaml` (`platform.tag`) move with it.
