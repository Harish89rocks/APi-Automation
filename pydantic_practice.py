from pydantic import BaseModel, ConfigDict, Field, ValidationError


class User(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=1)
    age: int = Field(gt=0)


test_cases = [
    {"name": "Harish", "age": 38},
    {"name": "Harish", "age": "38"},
    {"name": "", "age": 38},
    {"name": "Harish", "age": 0},
    {"name": "Harish", "age": 38, "role": "admin"},
]

for payload in test_cases:
    try:
        user = User(**payload)
        print("PASS:", user.model_dump())
    except ValidationError as error:
        print("REJECTED:", payload)
        print("Reason:", error.errors()[0]["msg"])
