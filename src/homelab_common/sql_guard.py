"""The no-raw-SQL rule (template/_standards/python.md), checked on the syntax tree, so quoting,
f-strings and calls split over lines can't slip past it."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_RAW_METHODS = {"exec_driver_sql", "executescript", "executemany"}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


def _is_sql_string(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str | bytes)
    if isinstance(node, ast.BinOp):  # "..." + "..." or "..." % (...)
        return _is_sql_string(node.left)
    return isinstance(node, ast.JoinedStr)


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.found: list[Violation] = []
        self.text_names: set[str] = set()  # names bound to sqlalchemy's text()
        self.sqlalchemy_modules: set[str] = set()  # `import sqlalchemy as sa` -> "sa"

    def _add(self, node: ast.AST, what: str) -> None:
        self.found.append(Violation(self.path, getattr(node, "lineno", 0), what))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] == "sqlite3":
                self._add(node, "import sqlite3")
            elif alias.name.startswith("sqlalchemy"):
                self.sqlalchemy_modules.add(alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.split(".")[0] == "sqlite3":
            self._add(node, "import from sqlite3")
        elif module.startswith("sqlalchemy"):
            for alias in node.names:
                if alias.name == "text":
                    self.text_names.add(alias.asname or alias.name)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.text_names:
            self._add(node, "sqlalchemy text()")
        elif isinstance(func, ast.Attribute):
            target = func.value
            if func.attr in _RAW_METHODS:
                self._add(node, f".{func.attr}()")
            elif (
                func.attr == "text"
                and isinstance(target, ast.Name)
                and target.id in self.sqlalchemy_modules
            ):
                self._add(node, "sqlalchemy text()")
            elif func.attr == "execute" and node.args and _is_sql_string(node.args[0]):
                self._add(node, ".execute() with a SQL string")
        self.generic_visit(node)


def check_file(path: Path) -> list[Violation]:
    visitor = _Visitor(path)
    visitor.visit(ast.parse(path.read_text(), filename=str(path)))
    return visitor.found


def python_files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
        else:
            yield from sorted(root.rglob("*.py"))
