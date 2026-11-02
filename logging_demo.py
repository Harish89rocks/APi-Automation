import asyncio

from logging_utils import configure_logging
from async_api_client import AsyncAPIClient


async def main():
    configure_logging()

    async with AsyncAPIClient(
        "https://jsonplaceholder.typicode.com"
    ) as client:
        user = await client.get_json(
            "/users/1",
            correlation_id="qa-demo-001",
        )
        print("User:", user["name"])


if __name__ == "__main__":
    asyncio.run(main())
