## Python

Base: [PEP 8](https://peps.python.org/pep-0008/). Its mechanical part is enforced, so review never repeats it:
ruff (`E W F I N B UP ANN`, `ruff format`) and pyright strict with `# type: ignore` disabled. `just check` runs both.

Deviation from PEP 8: line length is 100 (PEP 8 allows up to 99 by team agreement).

Review for the parts no tool checks:

- Names say what the thing is: no one-letter or cryptic abbreviations outside short loops and comprehensions.
- Consistency with the surrounding module beats a personal preference.
- Comments say why, not what, and stay true; no commented-out code.
- `is None` / `is not None` for None, `isinstance` for type checks.
- Catch the specific exception, with the smallest possible `try` body; never a bare `except`.
- A function either always returns a value or never does.
- A wire-format key that isn't snake_case (`apiVersion`) is a snake_case field with a Pydantic `alias`, never a mixedCase attribute.
- No `cast` to get a type checker green; fix the type.
- No raw SQL: every database read and write goes through SQLAlchemy ORM models and its query constructs (`select`, `insert`, `update`, `delete`), including third-party SQLite files and data changes in migrations. No SQL strings, `text()`, `exec_driver_sql`, `op.execute("...")` or `sqlite3`. Schema changes in migrations use Alembic ops. `just check` enforces it (ruff `S608` and a grep in `lint`).
