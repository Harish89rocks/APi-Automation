import asyncio
import time


async def simulate_api_call(user_id: int) -> dict:
    print(f"Starting request for user {user_id}")

    # Simulate waiting for an API response
    await asyncio.sleep(2)

    print(f"Finished request for user {user_id}")
    return {"id": user_id, "status": 200}


async def main():
    start = time.perf_counter()

    results = await asyncio.gather(
        simulate_api_call(1),
        simulate_api_call(2),
        simulate_api_call(3),
    )

    elapsed = time.perf_counter() - start

    print("Results:", results)
    print(f"Total time: {elapsed:.2f} seconds")


if __name__ == "__main__":
    asyncio.run(main())
