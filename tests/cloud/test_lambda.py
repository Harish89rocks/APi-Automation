import io
import json
import os
import zipfile

import pytest
from botocore.exceptions import ClientError

from services.aws import make_client

pytestmark = [pytest.mark.aws]

HANDLER_SOURCE = (
    "def handler(event, context):\n"
    "    return {'statusCode': 200, 'body': event.get('name', 'world')}\n"
)


def package(source: str = HANDLER_SOURCE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("lambda_function.py", source)
    return buffer.getvalue()


@pytest.fixture
def lambda_client(aws_mode):
    return make_client("lambda")


@pytest.fixture
def role_arn(aws_mode, unique_name) -> str:
    if aws_mode != "mock":
        arn = os.getenv("AWS_LAMBDA_ROLE_ARN")
        if not arn:
            pytest.skip("AWS_LAMBDA_ROLE_ARN not set (needed outside mock mode)")
        return arn

    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    iam = make_client("iam")
    role = iam.create_role(
        RoleName=unique_name, AssumeRolePolicyDocument=json.dumps(trust)
    )
    yield role["Role"]["Arn"]
    iam.delete_role(RoleName=unique_name)


@pytest.fixture
def function(lambda_client, unique_name, role_arn):
    lambda_client.create_function(
        FunctionName=unique_name,
        Runtime="python3.11",
        Role=role_arn,
        Handler="lambda_function.handler",
        Code={"ZipFile": package()},
        Timeout=10,
        MemorySize=128,
        Environment={"Variables": {"STAGE": "qa"}},
    )
    yield unique_name
    lambda_client.delete_function(FunctionName=unique_name)


# ---- configuration ---------------------------------------------------------------


def test_function_configuration_matches_deployment(lambda_client, function):
    config = lambda_client.get_function_configuration(FunctionName=function)

    assert config["Runtime"] == "python3.11"
    assert config["Handler"] == "lambda_function.handler"
    assert config["Timeout"] == 10
    assert config["MemorySize"] == 128
    assert config["Environment"]["Variables"] == {"STAGE": "qa"}


def test_function_is_listed(lambda_client, function):
    names = [
        f["FunctionName"]
        for page in lambda_client.get_paginator("list_functions").paginate()
        for f in page["Functions"]
    ]

    assert function in names


def test_configuration_update_is_applied(lambda_client, function):
    lambda_client.update_function_configuration(
        FunctionName=function, Timeout=30, MemorySize=256
    )

    config = lambda_client.get_function_configuration(FunctionName=function)

    assert (config["Timeout"], config["MemorySize"]) == (30, 256)


def test_function_timeout_is_within_budget(lambda_client, function):
    """Guard against functions drifting beyond the team's timeout budget."""
    budget = int(os.getenv("LAMBDA_MAX_TIMEOUT_S", "60"))

    config = lambda_client.get_function_configuration(FunctionName=function)

    assert config["Timeout"] <= budget


# ---- negative ----------------------------------------------------------------------


def test_missing_function_raises_not_found(lambda_client, unique_name):
    with pytest.raises(ClientError) as excinfo:
        lambda_client.get_function(FunctionName=f"{unique_name}-missing")

    assert excinfo.value.response["Error"]["Code"] == "ResourceNotFoundException"


def test_duplicate_function_name_is_rejected(lambda_client, function, role_arn):
    with pytest.raises(ClientError) as excinfo:
        lambda_client.create_function(
            FunctionName=function,
            Runtime="python3.11",
            Role=role_arn,
            Handler="lambda_function.handler",
            Code={"ZipFile": package()},
        )

    assert excinfo.value.response["Error"]["Code"] == "ResourceConflictException"


# ---- invocation (needs a real runtime; moto would require Docker) -----------------


@pytest.fixture
def invoking(aws_mode):
    if aws_mode == "mock":
        pytest.skip("invoking Lambda needs real AWS or LocalStack")


def test_invoke_returns_expected_payload(invoking, lambda_client, function):
    response = lambda_client.invoke(
        FunctionName=function,
        Payload=json.dumps({"name": "QA"}).encode(),
    )
    payload = json.loads(response["Payload"].read())

    assert response["StatusCode"] == 200
    assert "FunctionError" not in response
    assert payload == {"statusCode": 200, "body": "QA"}
