import asyncio

import httpx
import pytest


pytestmark = [pytest.mark.external]


@pytest.mark.asyncio
async def test_fetch_multiple_users_concurrently(external_api_url):
    semaphore = asyncio.Semaphore(3)

    async with httpx.AsyncClient(timeout=10) as client:

        async def fetch_user(user_id: int) -> dict:
            async with semaphore:
                response = await client.get(
                    f"{external_api_url}/users/{user_id}"
                )
                response.raise_for_status()
                return response.json()

        users = await asyncio.gather(
            *(fetch_user(user_id) for user_id in range(1, 6))
        )

    assert len(users) == 5
    assert all("id" in user and "name" in user for user in users)
    assert [user["id"] for user in users] == [1, 2, 3, 4, 5]
