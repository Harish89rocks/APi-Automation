import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from services.data_validation import (
    DataValidator,
    reconcile,
    run_table_checks,
    safe_identifier,
)

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_validator(rows, table="orders"):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        f"CREATE TABLE {table} (id INTEGER, email TEXT, amount REAL, updated_at TEXT)"
    )
    conn.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?)", rows)
    return DataValidator(lambda sql: conn.execute(sql).fetchall())


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


CLEAN = [
    (1, "a@x.com", 10.0, iso(1)),
    (2, "b@x.com", 20.0, iso(2)),
    (3, "c@x.com", 30.0, iso(3)),
]


# ---- individual checks ---------------------------------------------------------


def test_row_count():
    assert make_validator(CLEAN).row_count("orders") == 3


def test_row_count_of_empty_table_is_zero():
    assert make_validator([]).row_count("orders") == 0


def test_null_count():
    rows = CLEAN + [(4, None, 5.0, iso(1)), (5, None, 5.0, iso(1))]
    assert make_validator(rows).null_count("orders", "email") == 2


def test_duplicate_key_count_single_and_composite():
    rows = CLEAN + [(1, "other@x.com", 99.0, iso(1)), (1, "z@x.com", 1.0, iso(1))]
    v = make_validator(rows)

    assert v.duplicate_key_count("orders", ["id"]) == 1
    assert v.duplicate_key_count("orders", ["id", "email"]) == 0


@pytest.mark.parametrize(
    "minimum, maximum, expected",
    [(10, 30, 0), (11, 30, 1), (10, 29, 1), (None, 20, 1), (25, None, 2)],
    ids=["inclusive-bounds", "below-min", "above-max", "max-only", "min-only"],
)
def test_out_of_range_boundaries(minimum, maximum, expected):
    v = make_validator(CLEAN)

    assert v.out_of_range_count("orders", "amount", minimum, maximum) == expected


def test_out_of_range_requires_a_bound():
    with pytest.raises(ValueError):
        make_validator(CLEAN).out_of_range_count("orders", "amount")


def test_age_is_measured_from_latest_timestamp():
    v = make_validator(CLEAN)

    assert v.age("orders", "updated_at", now=NOW) == timedelta(hours=1)


def test_naive_timestamps_are_treated_as_utc():
    naive = [(1, "a@x.com", 1.0, "2026-01-01T11:00:00")]

    assert make_validator(naive).age("orders", "updated_at", now=NOW) == timedelta(hours=1)


def test_age_of_empty_table_is_none():
    assert make_validator([]).age("orders", "updated_at", now=NOW) is None


# ---- safety ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["orders; DROP TABLE orders", "o'rders", "1orders", "", "a b", "a.b.c.d", "x--", None],
)
def test_unsafe_identifiers_are_rejected(name):
    with pytest.raises(ValueError, match="Unsafe"):
        safe_identifier(name)


@pytest.mark.parametrize("name", ["orders", "DB.SCHEMA.ORDERS", "_t1", "s.t$1"])
def test_safe_identifiers_are_accepted(name):
    assert safe_identifier(name) == name


def test_injection_in_table_name_never_reaches_the_database():
    executed = []
    v = DataValidator(lambda sql: executed.append(sql) or [(0,)])

    with pytest.raises(ValueError):
        v.row_count("orders; DROP TABLE orders")

    assert executed == []


# ---- reconciliation ---------------------------------------------------------------


def test_reconcile_matching_counts():
    a, b = make_validator(CLEAN), make_validator(CLEAN, table="orders_copy")

    assert reconcile(a, b, "orders", "orders_copy") == []


def test_reconcile_detects_missing_rows():
    a = make_validator(CLEAN)
    b = make_validator(CLEAN[:2], table="orders_copy")

    problems = reconcile(a, b, "orders", "orders_copy")

    assert problems and "orders=3" in problems[0] and "orders_copy=2" in problems[0]


def test_reconcile_tolerance_boundary():
    rows = [(i, f"{i}@x.com", 1.0, iso(1)) for i in range(100)]
    a = make_validator(rows)
    b = make_validator(rows[:99], table="orders_copy")

    assert reconcile(a, b, "orders", "orders_copy", tolerance=0.01) == []
    assert reconcile(a, b, "orders", "orders_copy", tolerance=0.005) != []


def test_reconcile_rejects_negative_tolerance():
    a = make_validator(CLEAN)
    with pytest.raises(ValueError):
        reconcile(a, a, "orders", "orders", tolerance=-1)


# ---- spec-driven runner ------------------------------------------------------------

FULL_SPEC = {
    "name": "orders",
    "min_rows": 1,
    "max_rows": 10,
    "not_null": ["id", "email"],
    "unique": [["id"]],
    "ranges": [{"column": "amount", "min": 0, "max": 100}],
    "freshness": {"column": "updated_at", "max_age_hours": 24},
}


def test_clean_table_passes_full_spec():
    v = make_validator([(1, "a@x.com", 10.0, datetime.now(timezone.utc).isoformat())])

    assert run_table_checks(v, FULL_SPEC) == []


def test_each_defect_is_reported_with_context():
    rows = [
        (1, None, -5.0, iso(100)),
        (1, "dup@x.com", 500.0, iso(100)),
    ]

    failures = run_table_checks(make_validator(rows), FULL_SPEC)
    text = "\n".join(failures)

    assert "orders.email: 1 NULL" in text
    assert "orders(id): 1 duplicated" in text
    assert "orders.amount: 2 value(s) out of range" in text
    assert "orders.updated_at: data is" in text
    assert len(failures) == 4


def test_row_count_bounds_are_enforced():
    too_few = run_table_checks(make_validator([]), {"name": "orders", "min_rows": 1})
    too_many = run_table_checks(make_validator(CLEAN), {"name": "orders", "max_rows": 2})

    assert "min_rows" in too_few[0]
    assert "max_rows" in too_many[0]


def test_empty_table_with_freshness_is_flagged():
    spec = {"name": "orders", "freshness": {"column": "updated_at", "max_age_hours": 1}}

    assert "no timestamps" in run_table_checks(make_validator([]), spec)[0]
