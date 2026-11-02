import os
import time

import pytest
from botocore.exceptions import ClientError

from services.aws import make_client, rds_violations

pytestmark = [pytest.mark.aws]


@pytest.fixture
def rds(aws_mode):
    return make_client("rds")


@pytest.fixture
def logs(aws_mode):
    return make_client("logs")


@pytest.fixture
def cloudwatch(aws_mode):
    return make_client("cloudwatch")


def create_instance(rds, identifier, **overrides):
    params = dict(
        DBInstanceIdentifier=identifier,
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="qa_admin",
        MasterUserPassword=os.getenv("RDS_TEST_PASSWORD", "mock-only-Passw0rd!"),
        AllocatedStorage=20,
        StorageEncrypted=True,
        PubliclyAccessible=False,
        BackupRetentionPeriod=7,
        DeletionProtection=False,
    )
    params.update(overrides)
    rds.create_db_instance(**params)
    return rds.describe_db_instances(DBInstanceIdentifier=identifier)[
        "DBInstances"
    ][0]


# ---- RDS compliance checker ------------------------------------------------------


@pytest.fixture
def mock_only(aws_mode):
    if aws_mode != "mock":
        pytest.skip("creates throwaway RDS instances; mock mode only")


def test_compliant_instance_has_no_violations(mock_only, rds, unique_name):
    instance = create_instance(rds, unique_name)
    try:
        # DeletionProtection=False is flagged by policy, so ignore it here.
        problems = [p for p in rds_violations(instance) if "deletion" not in p]
        assert problems == []
        assert instance["Engine"] == "postgres"
    finally:
        rds.delete_db_instance(
            DBInstanceIdentifier=unique_name, SkipFinalSnapshot=True
        )


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"StorageEncrypted": False}, "storage is not encrypted"),
        ({"PubliclyAccessible": True}, "instance is publicly accessible"),
        ({"BackupRetentionPeriod": 0}, "automated backups are disabled"),
    ],
    ids=["unencrypted", "public", "no-backups"],
)
def test_non_compliant_instance_is_flagged(
    mock_only, rds, unique_name, overrides, expected
):
    instance = create_instance(rds, unique_name, **overrides)
    try:
        assert expected in rds_violations(instance)
    finally:
        rds.delete_db_instance(
            DBInstanceIdentifier=unique_name, SkipFinalSnapshot=True
        )


def test_checker_handles_missing_fields():
    assert "storage is not encrypted" in rds_violations({})


def test_existing_rds_instance_is_compliant():
    """Audit a real instance named by AWS_RDS_INSTANCE_ID (opt-in)."""
    identifier = os.getenv("AWS_RDS_INSTANCE_ID")
    if not identifier:
        pytest.skip("AWS_RDS_INSTANCE_ID not set")

    instance = make_client("rds").describe_db_instances(
        DBInstanceIdentifier=identifier
    )["DBInstances"][0]

    assert rds_violations(instance) == []


def test_unknown_instance_raises_not_found(rds, unique_name):
    with pytest.raises(ClientError) as excinfo:
        rds.describe_db_instances(DBInstanceIdentifier=f"{unique_name}-none")

    assert excinfo.value.response["Error"]["Code"] == "DBInstanceNotFound"


# ---- CloudWatch Logs: diagnostic evidence ------------------------------------------


@pytest.fixture
def log_stream(logs, unique_name):
    group = f"/qa/{unique_name}"
    logs.create_log_group(logGroupName=group)
    logs.create_log_stream(logGroupName=group, logStreamName="run-1")
    yield group, "run-1"
    logs.delete_log_group(logGroupName=group)


def now_ms() -> int:
    return int(time.time() * 1000)


def test_log_events_are_retrievable_in_order(logs, log_stream):
    group, stream = log_stream
    base = now_ms()
    logs.put_log_events(
        logGroupName=group,
        logStreamName=stream,
        logEvents=[
            {"timestamp": base + i, "message": f"step-{i}"} for i in range(3)
        ],
    )

    events = logs.get_log_events(
        logGroupName=group, logStreamName=stream, startFromHead=True
    )["events"]

    assert [e["message"] for e in events] == ["step-0", "step-1", "step-2"]


def test_filter_finds_error_events_only(logs, log_stream):
    group, stream = log_stream
    base = now_ms()
    logs.put_log_events(
        logGroupName=group,
        logStreamName=stream,
        logEvents=[
            {"timestamp": base, "message": "INFO started"},
            {"timestamp": base + 1, "message": "ERROR boom"},
            {"timestamp": base + 2, "message": "INFO done"},
        ],
    )

    found = logs.filter_log_events(
        logGroupName=group, filterPattern="ERROR"
    )["events"]

    assert [e["message"] for e in found] == ["ERROR boom"]


def test_logging_to_missing_group_fails(logs, unique_name):
    with pytest.raises(ClientError) as excinfo:
        logs.put_log_events(
            logGroupName=f"/qa/{unique_name}-none",
            logStreamName="x",
            logEvents=[{"timestamp": now_ms(), "message": "m"}],
        )

    assert excinfo.value.response["Error"]["Code"] == "ResourceNotFoundException"


# ---- CloudWatch metrics and alarms --------------------------------------------------


def test_custom_metric_is_published_and_aggregated(cloudwatch, unique_name):
    namespace = f"QA/{unique_name}"
    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {"MetricName": "Latency", "Value": value, "Unit": "Milliseconds"}
            for value in (100.0, 200.0, 300.0)
        ],
    )

    stats = cloudwatch.get_metric_statistics(
        Namespace=namespace,
        MetricName="Latency",
        StartTime=time.time() - 300,
        EndTime=time.time() + 300,
        Period=300,
        Statistics=["Average", "Maximum", "SampleCount"],
    )["Datapoints"]

    assert sum(p["SampleCount"] for p in stats) == 3
    assert max(p["Maximum"] for p in stats) == 300.0


def test_alarm_threshold_is_configured(cloudwatch, unique_name):
    cloudwatch.put_metric_alarm(
        AlarmName=unique_name,
        Namespace="QA/api",
        MetricName="5xxErrors",
        Statistic="Sum",
        Period=60,
        EvaluationPeriods=1,
        Threshold=5.0,
        ComparisonOperator="GreaterThanThreshold",
    )
    try:
        alarm = cloudwatch.describe_alarms(AlarmNames=[unique_name])[
            "MetricAlarms"
        ][0]

        assert alarm["Threshold"] == 5.0
        assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
    finally:
        cloudwatch.delete_alarms(AlarmNames=[unique_name])
