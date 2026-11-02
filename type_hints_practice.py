def validate_status(
    actual_status: int,
    expected_status: int
) -> bool:
    return actual_status == expected_status


print(validate_status("200", 200))
