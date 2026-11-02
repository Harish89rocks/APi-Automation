import os
import uuid
from contextlib import ExitStack
from unittest import mock

import pytest

from services.aws import make_client

FAKE_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
}


@pytest.fixture(scope="session")
def aws_mode() -> str:
    """mock (default) | endpoint (AWS_ENDPOINT_URL) | real (AWS_TEST_MODE=real)."""
    pytest.importorskip("boto3")
    if os.getenv("AWS_TEST_MODE") == "real":
        return "real"
    if os.getenv("AWS_ENDPOINT_URL"):
        return "endpoint"
    pytest.importorskip("moto")
    return "mock"


@pytest.fixture(scope="session", autouse=True)
def _aws_environment(aws_mode):
    """Keep mock runs away from real credentials and real AWS."""
    with ExitStack() as stack:
        if aws_mode == "mock":
            from moto import mock_aws

            stack.enter_context(mock.patch.dict(os.environ, FAKE_CREDENTIALS))
            stack.enter_context(mock_aws())
        yield


@pytest.fixture
def unique_name() -> str:
    return f"qa-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def s3(aws_mode):
    return make_client("s3")


@pytest.fixture
def bucket(s3, unique_name):
    """A bucket that is emptied and deleted after the test."""
    s3.create_bucket(Bucket=unique_name)
    yield unique_name

    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=unique_name):
        for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
            s3.delete_object(
                Bucket=unique_name, Key=item["Key"], VersionId=item["VersionId"]
            )
    s3.delete_bucket(Bucket=unique_name)
