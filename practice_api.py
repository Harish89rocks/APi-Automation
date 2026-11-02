from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, Field, field_validator

app = FastAPI(title="QA Negative Testing Practice API")

MAX_EMAIL_LOCAL_PART = 64  # RFC 5321


class User(BaseModel):
    name: str = Field(min_length=1, pattern=r".*\S.*")
    email: EmailStr

    @field_validator("email")
    @classmethod
    def local_part_within_rfc_limit(cls, value: str) -> str:
        if len(value.rsplit("@", 1)[0]) > MAX_EMAIL_LOCAL_PART:
            raise ValueError("email local part exceeds 64 characters")
        return value


class CreateUserResponse(BaseModel):
    message: str
    user: User


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/users", status_code=201, response_model=CreateUserResponse)
def create_user(user: User):
    return {
        "message": "User created successfully",
        "user": user
    }
