import asyncio


async def call_service(service_id: int) -> dict:
    await asyncio.sleep(0.5)

    if service_id == 3:
        raise RuntimeError("Service 3 failed")

    return {
        "service_id": service_id,
        "status": "success",
    }


async def main():
    results = await asyncio.gather(
        *(call_service(i) for i in range(1, 6)),
        return_exceptions=True,
    )

    successful_results = []
    failures = []

    for result in results:
        if isinstance(result, Exception):
            failures.append(str(result))
        else:
            successful_results.append(result)

    print("Successful results:", successful_results)
    print("Failures:", failures)
    print("Success count:", len(successful_results))
    print("Failure count:", len(failures))


if __name__ == "__main__":
    asyncio.run(main())
