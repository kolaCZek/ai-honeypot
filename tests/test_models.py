import pytest
from sqlalchemy import select

from shared.db import init_db, make_engine, make_session_factory
from shared.models import CredentialAttempt, IPUniverse, LinkEdge, Page, RequestLog


@pytest.fixture
async def session_factory():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    yield make_session_factory(engine)
    await engine.dispose()


async def test_create_and_read_all(session_factory):
    async with session_factory() as s:
        s.add(IPUniverse(ip="1.2.3.4", ua="curl/8", request_count=1))
        await s.commit()

        s.add_all([
            Page(ip="1.2.3.4", path="/", content_type="text/html",
                 body="<html/>", tokens_in=10, tokens_out=20),
            LinkEdge(ip="1.2.3.4", from_path="/", to_path="/admin"),
            RequestLog(ip="1.2.3.4", method="GET", path="/", status=200,
                       was_generated=True, was_bait=False),
            CredentialAttempt(ip="1.2.3.4", path="/login",
                              username="admin", password="hunter2"),
        ])
        await s.commit()

    async with session_factory() as s:
        ip = (await s.execute(select(IPUniverse))).scalar_one()
        assert ip.ip == "1.2.3.4"
        assert (await s.execute(select(Page))).scalar_one().tokens_in == 10
        assert (await s.execute(select(LinkEdge))).scalar_one().to_path == "/admin"
        assert (await s.execute(select(RequestLog))).scalar_one().was_generated is True
        assert (await s.execute(select(CredentialAttempt))).scalar_one().password == "hunter2"
