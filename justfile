# The single definition of "passes" (SPEC section 9). Run: uvx --from rust-just just check

check: sync lint types test secrets-guard

sync:
    uv sync --locked

lint:
    uv run ruff check
    uv run ruff format --check
    ! grep -rnE 'import sqlite3|[^a-z_]text\(|exec_driver_sql|executescript|\.executemany\(|op\.execute\("' src/ || { echo 'raw SQL found (use SQLAlchemy ORM)' >&2; exit 1; }

types:
    uv run pyright

test:
    uv run pytest

# every tracked *.enc.env must be SOPS-encrypted
secrets-guard:
    #!/usr/bin/env bash
    set -euo pipefail
    bad=0
    for f in $(git ls-files '*.enc.env'); do
        grep -q '^sops_mac=' "$f" || { echo "not SOPS-encrypted: $f" >&2; bad=1; }
    done
    exit $bad
