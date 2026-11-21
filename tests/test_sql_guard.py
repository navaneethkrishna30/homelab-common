from pathlib import Path

import pytest

from homelab_common.cli import main
from homelab_common.sql_guard import check_file


def _found(tmp_path: Path, source: str) -> list[str]:
    f = tmp_path / "m.py"
    f.write_text(source)
    return [v.what for v in check_file(f)]


@pytest.mark.parametrize(
    "source",
    [
        "import sqlite3\n",
        "from sqlite3 import connect\n",
        "from sqlalchemy import text\ntext('SELECT 1')\n",
        "from sqlalchemy.sql import text as t\nt('SELECT 1')\n",
        "import sqlalchemy as sa\nsa.text('SELECT 1')\n",
        "op.execute('UPDATE x SET y = 1')\n",
        "op.execute(f'DELETE FROM {t}')\n",
        'op.execute(\n    "UPDATE x"\n    " SET y = 1"\n)\n',
        "session.execute('SELECT ' + cols)\n",
        "conn.exec_driver_sql(q)\n",
        "cur.executemany(q, rows)\n",
    ],
)
def test_raw_sql_is_found(tmp_path: Path, source: str) -> None:
    assert _found(tmp_path, source)


@pytest.mark.parametrize(
    "source",
    [
        "session.execute(select(Day))\n",
        "op.execute(table.update().values(y=1))\n",
        "r.text()\n",  # not sqlalchemy's text
        "def text(x): ...\ntext('hi')\n",
    ],
)
def test_orm_code_passes(tmp_path: Path, source: str) -> None:
    assert _found(tmp_path, source) == []


def test_reports_line_number(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("x = 1\nop.execute('DROP TABLE x')\n")
    assert [v.line for v in check_file(f)] == [2]


def test_cli_fails_on_raw_sql(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("import sqlite3\n")
    assert main(["check-sql", str(tmp_path)]) == 1


def test_cli_passes_clean_tree(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("x = 1\n")
    assert main(["check-sql", str(tmp_path)]) == 0


def test_cli_missing_path_is_a_usage_error(tmp_path: Path) -> None:
    assert main(["check-sql", str(tmp_path / "nope")]) == 2
