import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

pytestmark = [pytest.mark.unit]


class User(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=1)
    age: int = Field(gt=0)


def test_valid_user_is_accepted():
    user = User(name="Harish", age=38)

    assert user.name == "Harish"
    assert user.age == 38


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Harish", "age": "38"},
        {"name": "", "age": 38},
        {"name": "Harish", "age": 0},
        {"name": "Harish", "age": 38, "role": "admin"},
    ],
)
def test_invalid_user_is_rejected(payload):
    with pytest.raises(ValidationError):
        User(**payload)
