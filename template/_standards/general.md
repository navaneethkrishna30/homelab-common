## Every change

Nav rarely reads code; agents maintain it. Leave the repo smaller and easier to navigate, not bigger.

Restraint:

- A request is a change, not a policy. "Remove X" deletes X with its code, config, docs and tests; no guards, checks
  or tests that X stays gone. The same for rename, move, stop doing.
- All of what was asked and nothing more. Anything else worth fixing is listed for Nav, not done.
- Nothing for a case that doesn't exist yet: no abstraction, interface, option, flag, config key or "for later" code
  until a second real use appears.
- Deletion beats addition. A diff bigger than the problem is cut down; replaced code is deleted in the same change.
- Extend what exists (component, hook, client, helper, rule); never build a second one.
- Smallest change that does the job: no drive-by refactors, renames or reformatting.
- No new dependency without Nav's yes.
- Edit existing files over adding new ones; no dead code or `v2` files.
- One owner per decision (statuses, colours, data fetching, page lists), never a second place.
- Split a file over about 300 lines only along a real seam, and only in the area being changed.

Types:

- Every function has typed parameters and a declared return type; every value's type is known. No `any` / `Any`, no
  untyped values.
- Anything passed between modules or services is a declared type (Python: a Pydantic model), never a bare dict.
- Type checkers are never silenced to get green; fix the type.

Tests:

- Test logic that decides or parses (rules, conversions, parsers, access checks): one case per outcome. No tests for
  library components, layouts, snapshots or trivial getters.
- A test earns its place only if its failure means a bug Nav would notice and it is still worth keeping a year from
  now. No tests that pin the last instruction, raise a count or prove something was removed.
- A bug fix gets at most one regression test, at the level where the bug lived, and only if it could plausibly return.
- A behaviour change updates or deletes the old behaviour's tests; it doesn't stack new ones beside them.
