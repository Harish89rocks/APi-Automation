import hashlib

import pytest
from botocore.exceptions import ClientError

from services.aws import s3_bucket_violations

pytestmark = [pytest.mark.aws]


def error_code(excinfo) -> str:
    return excinfo.value.response["Error"]["Code"]


# ---- object round-trip ---------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [b"", b"x", b"hello world", b"\x00\xff" * 1024, b"z" * (1024 * 1024)],
    ids=["empty", "1-byte", "text", "binary", "1MiB"],
)
def test_object_round_trip_preserves_bytes(s3, bucket, body):
    s3.put_object(Bucket=bucket, Key="data.bin", Body=body)

    stored = s3.get_object(Bucket=bucket, Key="data.bin")["Body"].read()

    assert stored == body
    assert hashlib.md5(stored).hexdigest() == hashlib.md5(body).hexdigest()


def test_metadata_and_content_type_are_stored(s3, bucket):
    s3.put_object(
        Bucket=bucket,
        Key="doc.json",
        Body=b"{}",
        ContentType="application/json",
        Metadata={"source": "qa"},
    )

    head = s3.head_object(Bucket=bucket, Key="doc.json")

    assert head["ContentType"] == "application/json"
    assert head["Metadata"] == {"source": "qa"}
    assert head["ContentLength"] == 2


def test_overwrite_returns_latest_content(s3, bucket):
    s3.put_object(Bucket=bucket, Key="k", Body=b"one")
    s3.put_object(Bucket=bucket, Key="k", Body=b"two")

    assert s3.get_object(Bucket=bucket, Key="k")["Body"].read() == b"two"


def test_versioning_keeps_history(s3, bucket):
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    first = s3.put_object(Bucket=bucket, Key="k", Body=b"one")["VersionId"]
    s3.put_object(Bucket=bucket, Key="k", Body=b"two")

    old = s3.get_object(Bucket=bucket, Key="k", VersionId=first)["Body"].read()

    assert old == b"one"


def test_listing_paginates_without_loss_or_duplicates(s3, bucket):
    keys = {f"items/{i:03d}" for i in range(7)}
    for key in keys:
        s3.put_object(Bucket=bucket, Key=key, Body=b"x")

    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="items/", PaginationConfig={"PageSize": 2}
    )
    listed = [o["Key"] for page in pages for o in page.get("Contents", [])]

    assert len(listed) == len(set(listed)) == 7
    assert set(listed) == keys


def test_prefix_listing_is_scoped(s3, bucket):
    s3.put_object(Bucket=bucket, Key="a/1", Body=b"x")
    s3.put_object(Bucket=bucket, Key="b/1", Body=b"x")

    listed = s3.list_objects_v2(Bucket=bucket, Prefix="a/")["Contents"]

    assert [o["Key"] for o in listed] == ["a/1"]


# ---- negative -------------------------------------------------------------------


def test_missing_key_raises_no_such_key(s3, bucket):
    with pytest.raises(ClientError) as excinfo:
        s3.get_object(Bucket=bucket, Key="absent")

    assert error_code(excinfo) == "NoSuchKey"


def test_missing_bucket_raises_no_such_bucket(s3, unique_name):
    with pytest.raises(ClientError) as excinfo:
        s3.list_objects_v2(Bucket=f"{unique_name}-missing")

    assert error_code(excinfo) == "NoSuchBucket"


def test_head_on_missing_key_is_404(s3, bucket):
    with pytest.raises(ClientError) as excinfo:
        s3.head_object(Bucket=bucket, Key="absent")

    assert excinfo.value.response["ResponseMetadata"]["HTTPStatusCode"] == 404


def test_deleting_missing_key_is_idempotent(s3, bucket):
    response = s3.delete_object(Bucket=bucket, Key="absent")

    assert response["ResponseMetadata"]["HTTPStatusCode"] in (200, 204)


def test_non_empty_bucket_cannot_be_deleted(s3, bucket):
    s3.put_object(Bucket=bucket, Key="k", Body=b"x")

    with pytest.raises(ClientError) as excinfo:
        s3.delete_bucket(Bucket=bucket)

    assert error_code(excinfo) == "BucketNotEmpty"


@pytest.mark.parametrize(
    "name",
    ["ab", "a" * 64],
    ids=["below-3-chars", "above-63-chars"],
)
def test_bucket_name_length_boundaries_are_rejected(s3, name):
    with pytest.raises(ClientError) as excinfo:
        s3.create_bucket(Bucket=name)

    assert error_code(excinfo) == "InvalidBucketName"


# ---- security baseline checker ---------------------------------------------------


def test_insecure_bucket_is_flagged(s3, bucket):
    problems = s3_bucket_violations(s3, bucket)

    assert "no public access block configured" in problems
    assert "default encryption is not configured" in problems


def test_hardened_bucket_passes(s3, bucket):
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        },
    )

    assert s3_bucket_violations(s3, bucket) == []
