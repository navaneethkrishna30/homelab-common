"""The `sql` tool (SPEC section 3): one read-only statement per call, as the jarvis_ro role."""

from datetime import date, datetime

from fastapi import FastAPI
from pydantic import BaseModel, JsonValue

from homelab_common import CommonSettings, create_app, db, load_config, tool

MAX_ROWS = 200


class Settings(CommonSettings):
    """Nothing beyond the common settings."""


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[JsonValue]]
    truncated: bool


def _json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


@tool
async def query(sql: str) -> QueryResult:
    """Run ONE read-only SQL statement on the homelab database (10 s limit, at most 200 rows).

    Only the audit log is readable: `SELECT ... FROM common.audit`.
    """
    async with db.session() as session:
        connection = await session.connection()
        await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        await connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
        # Straight to the driver: a second statement is refused; ":name" in the text is no bind.
        result = await connection.exec_driver_sql(sql)
        fetched = result.fetchmany(MAX_ROWS + 1)
        return QueryResult(
            columns=list(result.keys()),
            rows=[[_json(value) for value in row] for row in fetched[:MAX_ROWS]],
            truncated=len(fetched) > MAX_ROWS,
        )


app: FastAPI = create_app("sql", load_config(Settings), routers=[], tools=[query])
