"""AWS helpers. Credentials come from the standard AWS chain / environment only.

Modes (selected in tests/cloud/conftest.py):
  mock      default; moto in-process, no network, no credentials needed
  endpoint  AWS_ENDPOINT_URL set (e.g. LocalStack)
  real      AWS_TEST_MODE=real; uses your normal AWS credentials
"""

import os

DEFAULT_REGION = "us-east-1"


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
