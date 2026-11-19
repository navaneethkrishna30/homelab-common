import os
from collections.abc import AsyncGenerator

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from homelab_common import CommonSettings, db


def settings_for(url: str, schema: str) -> CommonSettings:
    parsed = make_url(url)
    return CommonSettings(
        service_name="dbtest",
        public_path="/dbtest",
        database_host=parsed.host or "",
        database_port=parsed.port or 5432,
        database_name=parsed.database or "",
        database_schema=schema,
        database_user=parsed.username or "",
        database_password=SecretStr(parsed.password or ""),
        db_pool_size=2,
    )


@pytest.fixture(autouse=True)
async def clean_module() -> AsyncGenerator[None]:
    yield
    await db.dispose()


async def test_session_before_init_raises() -> None:
    with pytest.raises(RuntimeError, match="not called"):
        async with db.session():
            pass


async def test_init_twice_raises() -> None:
    settings = settings_for("postgresql://u:p@localhost/x", "s")
    db.init(settings)
    with pytest.raises(RuntimeError, match="already"):
        db.init(settings)


async def test_ping_false_before_init() -> None:
    assert await db.ping() is False


@pytest.mark.integration
class TestWithPostgres:
    @pytest.fixture
    async def url(self) -> AsyncGenerator[str]:
        url = os.environ.get("HOMELAB_TEST_DATABASE_URL")
        if url is None:
            pytest.skip("HOMELAB_TEST_DATABASE_URL not set")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS dbtest CASCADE"))
            await conn.execute(text("CREATE SCHEMA dbtest"))
        yield url
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA dbtest CASCADE"))
        await engine.dispose()

    async def test_search_path_and_ping(self, url: str) -> None:
        db.init(settings_for(url, "dbtest"))
        assert await db.ping() is True
        async with db.session() as s:
            assert (await s.execute(text("SHOW search_path"))).scalar_one() == "dbtest"

    async def test_commit_on_clean_exit(self, url: str) -> None:
        db.init(settings_for(url, "dbtest"))
        async with db.session() as s:
            await s.execute(text("CREATE TABLE t (n int)"))
            await s.execute(text("INSERT INTO t VALUES (1)"))
        async with db.session() as s:
            assert (await s.execute(text("SELECT count(*) FROM t"))).scalar_one() == 1

    async def test_rollback_on_error(self, url: str) -> None:
        db.init(settings_for(url, "dbtest"))
        async with db.session() as s:
            await s.execute(text("CREATE TABLE t (n int)"))
        with pytest.raises(ValueError, match="boom"):
            async with db.session() as s:
                await s.execute(text("INSERT INTO t VALUES (1)"))
                raise ValueError("boom")
        async with db.session() as s:
            assert (await s.execute(text("SELECT count(*) FROM t"))).scalar_one() == 0
