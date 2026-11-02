"""AWS helpers. Credentials come from the standard AWS chain / environment only.

Modes (selected in tests/cloud/conftest.py):
  mock      default; moto in-process, no network, no credentials needed
  endpoint  AWS_ENDPOINT_URL set (e.g. LocalStack)
  real      AWS_TEST_MODE=real; uses your normal AWS credentials
"""

import os

from services.config import ConfigurationError

DEFAULT_REGION = "us-east-1"
DEFAULT_BUCKET_PREFIX = "qa-"


def bucket_prefix() -> str:
    return os.getenv("AWS_TEST_BUCKET_PREFIX", DEFAULT_BUCKET_PREFIX)


def require_test_owned(bucket: str) -> None:
    """Cleanup guard: only buckets carrying the test prefix may be emptied/deleted."""
    prefix = bucket_prefix()
    if len(prefix) < 3 or not bucket.startswith(prefix):
        raise RuntimeError(
            f"Refusing to modify bucket {bucket!r}: not created by this test "
            f"run (expected prefix {prefix!r}, minimum 3 characters)"
        )


def assert_expected_account(sts_client, expected_account_id: str | None) -> str:
    """Real AWS only: refuse to run unless the caller is the allow-listed account."""
    if not expected_account_id:
        raise ConfigurationError(
            "AWS_TEST_MODE=real requires AWS_TEST_ALLOWED_ACCOUNT_ID so tests "
            "can never run against an unintended (e.g. production) account"
        )
    actual = sts_client.get_caller_identity()["Account"]
    if actual != expected_account_id:
        raise ConfigurationError(
            f"Credentials belong to account {actual}, but "
            f"AWS_TEST_ALLOWED_ACCOUNT_ID is {expected_account_id}; refusing to run"
        )
    return actual


def region() -> str:
    return os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or DEFAULT_REGION


def make_client(service: str):
    import boto3

    kwargs = {"region_name": region()}
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(service, **kwargs)


def rds_violations(instance: dict) -> list[str]:
    """Return policy violations for a ``describe_db_instances`` entry."""
    problems = []
    if not instance.get("StorageEncrypted"):
        problems.append("storage is not encrypted")
    if instance.get("PubliclyAccessible"):
        problems.append("instance is publicly accessible")
    if instance.get("BackupRetentionPeriod", 0) < 1:
        problems.append("automated backups are disabled")
    if instance.get("DeletionProtection") is False:
        problems.append("deletion protection is off")
    if instance.get("DBInstanceStatus") != "available":
        problems.append(f"status is {instance.get('DBInstanceStatus')!r}")
    return problems


def s3_bucket_violations(s3, bucket: str) -> list[str]:
    """Return security-baseline violations for an S3 bucket."""
    from botocore.exceptions import ClientError

    problems = []

    try:
        config = s3.get_public_access_block(Bucket=bucket)[
            "PublicAccessBlockConfiguration"
        ]
        if not all(config.values()):
            problems.append("public access block is not fully enabled")
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchPublicAccessBlockConfiguration":
            raise
        problems.append("no public access block configured")

    try:
        s3.get_bucket_encryption(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ServerSideEncryptionConfigurationNotFoundError":
            raise
        problems.append("default encryption is not configured")

    return problems
