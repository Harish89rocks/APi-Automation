class APIValidationError(Exception):
    """Raised when an API response fails validation."""


def validate_status(actual_status: int, expected_status: int) -> bool:
    if actual_status != expected_status:
        raise APIValidationError(
            f"Expected HTTP {expected_status}, but received {actual_status}"
        )

    return True


test_cases = [
    (200, 200),
    (500, 200),
    (201, 201),
]

for actual, expected in test_cases:
    try:
        result = validate_status(actual, expected)
        print(f"PASS: HTTP {actual} matched expected {expected}: {result}")

    except APIValidationError as error:
        print(f"VALIDATION FAILURE: {error}")

    except Exception as error:
        print(f"UNEXPECTED ERROR: {type(error).__name__}: {error}")
