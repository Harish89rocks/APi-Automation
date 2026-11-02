import time
from functools import wraps


def measure_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start

        print(f"Function: {func.__name__}")
        print(f"Result: {result}")
        print(f"Duration: {elapsed:.4f} seconds")

        return result

    return wrapper


@measure_time
def validate_status(actual_status, expected_status):
    return actual_status == expected_status


validate_status(200, 200)
validate_status(404, 200)
