"""The `homelab-common` command line (SPEC section 4)."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from homelab_common.service_spec import load_service_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="homelab-common")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="check a service.yaml")
    validate.add_argument("path", type=Path, help="path to service.yaml")
    arguments = parser.parse_args(argv)

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
