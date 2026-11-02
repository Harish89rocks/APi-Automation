from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(title="QA Negative Testing Practice API")


class User(BaseModel):
    name: str = Field(min_length=1, pattern=r".*\S.*")
    email: EmailStr


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
