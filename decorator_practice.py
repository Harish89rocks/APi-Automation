import time
from functools import wraps


def measure_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()

        result = func(*args, **kwargs)

        elapsed = time.perf_counter() - start
        print(f"{func.__name__} took {elapsed:.2f} seconds")

        return result

    return wrapper


@measure_time
def api_check():
    time.sleep(1)
    return "PASS"


result = api_check()
print(result)
