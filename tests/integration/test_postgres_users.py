import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.database]

INSERT = "INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id"


def insert_user(db, name="Harish", email="harish@example.com") -> int:
    return db.execute(INSERT, (name, email)).fetchone()[0]


def count_users(db) -> int:
    return db.execute("SELECT count(*) FROM users").fetchone()[0]


def assert_rejected(db, error_type, name, email):
    """The insert must fail with ``error_type`` and leave no row behind."""
    with pytest.raises(error_type):
        with db.transaction():
            db.execute(INSERT, (name, email))


# ---- happy path and round-trip -----------------------------------------------


def test_insert_populates_generated_columns(db):
    user_id = insert_user(db)

    row = db.execute(
        "SELECT id, name, email, created_at FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()

    assert row[0] == user_id
    assert (row[1], row[2]) == ("Harish", "harish@example.com")
    assert row[3] is not None


@pytest.mark.parametrize(
    "name",
    ["H", "H" * 10_000, "Zoë Müller", "李雷", "  padded  "],
    ids=["min-length", "len-10000", "accented", "cjk", "padded"],
)
def test_name_round_trips_exactly(db, name):
    user_id = insert_user(db, name=name)

    stored = db.execute(
        "SELECT name FROM users WHERE id = %s", (user_id,)
    ).fetchone()[0]

    assert stored == name


def test_each_test_starts_with_an_empty_table(db):
    """Per-test rollback must isolate tests from one another."""
    assert count_users(db) == 0
    insert_user(db)
    assert count_users(db) == 1


# ---- constraints (negative) ------------------------------------------------


@pytest.mark.parametrize(
    "name, email",
    [(None, "a@example.com"), ("Harish", None)],
    ids=["null-name", "null-email"],
)
def test_nulls_are_rejected(db, name, email):
    assert_rejected(db, psycopg.errors.NotNullViolation, name, email)
    assert count_users(db) == 0


@pytest.mark.parametrize("name", ["", " ", "\t", "   \t  "])
def test_blank_name_is_rejected(db, name):
    assert_rejected(
        db, psycopg.errors.CheckViolation, name, "a@example.com"
    )


@pytest.mark.parametrize(
    "email",
    ["plainaddress", "@example.com", "user@", "user@@example.com",
     "user name@example.com", "user@nodot"],
)
def test_malformed_email_is_rejected(db, email):
    assert_rejected(db, psycopg.errors.CheckViolation, "H", email)


def test_duplicate_email_is_rejected_case_insensitively(db):
    insert_user(db, email="Harish@Example.com")

    assert_rejected(
        db, psycopg.errors.UniqueViolation, "Other", "harish@example.COM"
    )
    assert count_users(db) == 1


# ---- SQL-based data validation ----------------------------------------------


def test_no_duplicate_emails_after_bulk_load(db):
    for index in range(50):
        insert_user(db, name=f"User {index}", email=f"user{index}@example.com")

    duplicates = db.execute(
        "SELECT lower(email), count(*) FROM users "
        "GROUP BY lower(email) HAVING count(*) > 1"
    ).fetchall()

    assert duplicates == []
    assert count_users(db) == 50


def test_no_blank_or_null_values_after_bulk_load(db):
    for index in range(10):
        insert_user(db, name=f"User {index}", email=f"user{index}@example.com")

    invalid = db.execute(
        "SELECT count(*) FROM users "
        "WHERE name IS NULL OR btrim(name) = '' OR email IS NULL"
    ).fetchone()[0]

    assert invalid == 0


def test_sql_injection_payload_is_stored_literally(db):
    payload = "x'); DROP TABLE users;--"

    insert_user(db, name=payload)

    assert db.execute("SELECT name FROM users").fetchone()[0] == payload
    assert db.execute("SELECT to_regclass('users')").fetchone()[0] is not None


def test_failed_savepoint_discards_its_changes(db):
    insert_user(db, email="kept@example.com")

    with pytest.raises(RuntimeError):
        with db.transaction():
            insert_user(db, email="discarded@example.com")
            raise RuntimeError("force rollback")

    emails = [r[0] for r in db.execute("SELECT email FROM users").fetchall()]
    assert emails == ["kept@example.com"]


# ---- API and database agree ---------------------------------------------------

AGREEMENT_CASES = [
    ("Harish", "harish@example.com", True),
    ("H", "a@example.com", True),
    ("", "harish@example.com", False),
    ("   ", "harish@example.com", False),
    ("Harish", "not-an-email", False),
    ("Harish", "user@", False),
    ("Harish", "@example.com", False),
]


@pytest.mark.parametrize(
    "name, email, valid",
    AGREEMENT_CASES,
    ids=[f"{n!r}-{e!r}" for n, e, _ in AGREEMENT_CASES],
)
def test_database_enforces_the_same_rules_as_the_api(
    local_api, db, name, email, valid
):
    api_accepts = (
        local_api.post("/users", json={"name": name, "email": email})
        .status_code
        == 201
    )

    try:
        with db.transaction():
            db.execute(INSERT, (name, email))
        db_accepts = True
    except psycopg.errors.IntegrityError:
        db_accepts = False

    assert api_accepts == valid
    assert db_accepts == valid
