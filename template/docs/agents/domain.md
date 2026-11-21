# Domain Docs

How the engineering skills consume this repo's domain documentation. Layout: **single-context**.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root (this repo's name for what the skills call `CONTEXT.md`). Platform terms (service,
  gateway, schema, actor, audit, ...) are defined in homelab-common's
  [GLOSSARY.md](https://github.com/navaneethkrishna30/homelab-common/blob/main/GLOSSARY.md); link to it instead of
  redefining them, and use its words.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

When a skill says `CONTEXT.md`, use `GLOSSARY.md`. If a file is missing, proceed silently; `/domain-modeling`
creates entries when terms or decisions get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a test name), use the term as
`GLOSSARY.md` defines it. Don't drift to the synonyms it lists as avoided. A concept missing from the glossary is
either invented language (reconsider) or a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an ADR, say so rather than silently overriding:

> _Contradicts ADR-0004 (<its decision in a few words>), but worth reopening because…_
