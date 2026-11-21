"""The `homelab-common` command line (SPEC section 4)."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from homelab_common import sql_guard
from homelab_common.service_spec import load_service_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="homelab-common")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="check a service.yaml")
    validate.add_argument("path", type=Path, help="path to service.yaml")
    check_sql = subcommands.add_parser("check-sql", help="fail on raw SQL (use the SQLAlchemy ORM)")
    check_sql.add_argument("paths", type=Path, nargs="+", help="files or directories to scan")
    arguments = parser.parse_args(argv)

    if arguments.command == "check-sql":
        return _check_sql(arguments.paths)
    path: Path = arguments.path
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        spec = load_service_spec(path)
    except ValidationError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"ok: {spec.name}")
    return 0


def _check_sql(paths: list[Path]) -> int:
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"no such path: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2
    found = [v for f in sql_guard.python_files(paths) for v in sql_guard.check_file(f)]
    for violation in found:
        print(f"{violation}: raw SQL (use the SQLAlchemy ORM)", file=sys.stderr)
    return 1 if found else 0
