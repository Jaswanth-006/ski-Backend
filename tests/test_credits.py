"""Credit (receivables) tests (Phase E)."""

from __future__ import annotations

from app.core.config import settings
from app.db.models import Credit
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

PERSON = "ZZ-credit-Ravi"


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    return str(res.json()["access_token"])


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(delete(Credit).where(Credit.person_name == PERSON))
        await db.commit()
    await engine.dispose()


async def test_credit_create_list_and_settle(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        created = await http.post(
            "/v1/credits",
            headers=admin,
            json={"person_name": PERSON, "amount": 5000, "given_date": "2026-07-10"},
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json()["is_settled"] is False

        # Shows among open credits.
        open_list = (await http.get("/v1/credits?settled=false", headers=admin)).json()
        assert any(c["id"] == cid for c in open_list)

        # Settle it → moves out of the open list, gets a settled_date.
        settled = await http.post(f"/v1/credits/{cid}/settle", headers=admin)
        assert settled.status_code == 200
        assert settled.json()["is_settled"] is True
        assert settled.json()["settled_date"] is not None

        still_open = (await http.get("/v1/credits?settled=false", headers=admin)).json()
        assert all(c["id"] != cid for c in still_open)
    finally:
        await _cleanup()
