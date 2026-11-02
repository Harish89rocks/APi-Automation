# API Automation Framework

[![CI](https://github.com/Harish89rocks/APi-Automation/actions/workflows/ci.yml/badge.svg)](https://github.com/Harish89rocks/APi-Automation/actions/workflows/ci.yml)

Python 3.11 + pytest. Sync (`requests`) and async (`httpx`) clients, retry policy,
Pydantic validation, JSON logging.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `EXTERNAL_API_URL` | `https://jsonplaceholder.typicode.com` | Base URL for `external` tests |
| `OPENAPI_SPEC_URL` | unset (tests skip) | URL or JSON file path of a real backend's OpenAPI spec |
| `POSTGRES_DSN` | unset (DB tests skip) | Full PostgreSQL connection string; takes precedence |
| `POSTGRES_HOST` / `_PORT` / `_DB` / `_USER` / `_PASSWORD` | unset | Alternative to `POSTGRES_DSN` (port 5432, db/user `postgres` by default) |

DB tests create a uniquely named schema, run every test in a rolled-back transaction, and drop only that schema,
so they are safe on a shared database. Use a dedicated test database/user regardless.

### Deployment, cloud, warehouse and AI/ML (all opt-in; skip when unconfigured)

| Variable | Purpose |
|---|---|
| `AUTH_JWT_SECRET` / `AUTH_TOKEN_TTL_S` | Practice API token signing key (random per process if unset) and token lifetime (default 300s) |
| `DEPLOYED_API_URL` | Running instance (Docker/Compose, or `kubectl port-forward`) for `deployment` tests |
| `DEPLOYED_API_WAIT` / `DEPLOYED_API_MAX_LATENCY_S` | Readiness wait and latency budget for deployment tests |
| `AWS_ENDPOINT_URL` | LocalStack-style endpoint; default is in-process moto mock |
| `AWS_TEST_MODE=real` + `AWS_LAMBDA_ROLE_ARN` | Run against real AWS (use a sandbox account); credentials via the standard AWS chain |
| `AWS_RDS_INSTANCE_ID` | Enables the real-instance RDS compliance audit |
| `LAMBDA_MAX_TIMEOUT_S` | Lambda timeout policy limit |
| `SNOWFLAKE_ACCOUNT`, `_USER`, `_PASSWORD` or `_PRIVATE_KEY_PATH`, `_WAREHOUSE`, `_DATABASE`, `_SCHEMA`, `_ROLE` | Snowflake connection |
| `CLICKHOUSE_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_DATABASE`, `_SECURE` | ClickHouse connection |
| `WAREHOUSE_CHECKS_FILE` | JSON of table checks (see `warehouse_checks.example.json`) |
| `AI_API_URL`, `AI_API_KEY` | AI/ML service and optional bearer token |
| `AI_ENDPOINT`, `AI_PROMPT_FIELD`, `AI_TEXT_PATH` | Request/response shape (defaults `/predict`, `prompt`, `text`; dotted paths like `choices.0.message.content`) |
| `AI_EVAL_CASES_FILE` | JSON eval cases (see `ai_eval_cases.example.json`) |
| `AI_EVAL_THRESHOLDS_FILE`, `AI_MAX_LATENCY_S`, `AI_P95_LATENCY_S`, `AI_MIN_F1`, `AI_MAX_CHARS`, `AI_MIN_CHARS`, `AI_MIN_PASS_RATE` | Quality thresholds (env overrides file). Defaults are generic placeholders: tune per model |

Dependency files: `requirements.txt` (test framework), `requirements-app.txt` (app runtime / Docker image),
`requirements-cloud.txt` (adds boto3, moto, Snowflake, ClickHouse clients).

Never commit credentials; supply any future secrets through environment variables or CI secret stores.

## Test layers (pytest markers)

| Marker | Meaning |
|---|---|
| `unit` | Deterministic, no network |
| `integration` | Exercises the practice FastAPI app in-process (`local_api` fixture, no server needed) |
| `negative` | Invalid input / failure paths |
| `smoke` | Minimal health checks (deployment tests) |
| `deployment` | Against a running container/cluster (`DEPLOYED_API_URL`) |
| `aws` | S3/Lambda/RDS/CloudWatch (moto by default) |
| `warehouse` | Snowflake/ClickHouse live checks; validator logic tests run offline |
| `ai` | AI/ML schema, latency and quality evaluation; live tests need `AI_API_URL` |
| `auth` | OAuth2 client-credentials + JWT authentication/authorization (`auth_api.py`, `tests/test_auth_jwt.py`) |
| `contract` | OpenAPI/schema contract checks (`contract_utils.py`) |
| `database` | Needs PostgreSQL (`services/`); skipped when unconfigured |
| `external` | Calls a real third-party API; requires internet |

## Commands

```bash
pytest                                  # full suite (includes external tests)
pytest -m "not external"                # offline, deterministic suite (fast)
pytest -m unit                          # unit tests only
pytest -m "integration and negative"    # local API negative tests
pytest -m external                      # external API tests only
pytest -m contract                      # OpenAPI contract tests
POSTGRES_DSN=postgresql://user@host/db pytest -m database      # SQL integration tests
OPENAPI_SPEC_URL=http://host/openapi.json pytest -m contract   # also check a real backend spec
python -m pip install -r requirements-cloud.txt && pytest -m "aws or warehouse or ai"   # optional suites
DEPLOYED_API_URL=http://localhost:8000 pytest -m deployment    # after `docker compose up -d --build`
AI_API_URL=https://host AI_EVAL_CASES_FILE=ai_eval_cases.example.json pytest -m ai
pytest -m "not external" --html=artifacts/report.html --self-contained-html
```

## Integration setup and safety rules

All values below are **placeholders**. Never commit real credentials; use environment variables or CI secrets.

**Rule of thumb:** *absent* configuration → the suite is **skipped**; *present but broken or partial* configuration
→ the suite **fails** with an actionable message (it never silently skips).

| Situation | Result |
|---|---|
| Optional integration not configured | skipped (reason shown with `-ra`) |
| Configured but unreachable / invalid / partial | **failed** |
| Optional Python package missing (boto3, moto, …) | skipped locally; **failed** when `REQUIRE_OPTIONAL_DEPS=1` (set in CI) |
| Assertion fails | failed |
| `xfail` / `xpass` | known defect still failing / now fixed (investigate) |

### Local setup (offline)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-cloud.txt     # superset: framework + boto3/moto/Snowflake/ClickHouse
pytest -ra -m "not external and not database and not deployment"
```
`requirements.txt` includes `httpx2`, which removes Starlette's "Using httpx with starlette.testclient is
deprecated" warning (the only warning observed; it originated in `fastapi/testclient.py`).

### PostgreSQL
`POSTGRES_DSN=postgresql://USER:PASSWORD@HOST:5432/qa_test` or `POSTGRES_HOST/_PORT/_DB/_USER/_PASSWORD`.
The database name must contain `test` or start with `qa`, else tests refuse to run
(override deliberately with `POSTGRES_ALLOW_NON_TEST_DB=1`). Tests only touch a per-run `qa_<uuid>` schema inside a
rolled-back transaction. Run: `pytest -ra -m database`.
Quick local DB: `docker run -d -p 5432:5432 -e POSTGRES_DB=qa_test -e POSTGRES_PASSWORD=CHANGE_ME postgres:16-alpine`.

### AWS (S3 / Lambda / RDS / CloudWatch)
`boto3`/`moto` are in `requirements-cloud.txt`. Default is an in-process mock; `AWS_ENDPOINT_URL` targets LocalStack.
`AWS_TEST_MODE=real` additionally **requires** `AWS_TEST_ALLOWED_ACCOUNT_ID=<sandbox account id>` (checked via STS).
Buckets are created with prefix `AWS_TEST_BUCKET_PREFIX` (default `qa-`) and cleanup refuses to touch any other bucket.
Run: `pytest -ra -m aws`.

### Deployed API
`DEPLOYED_API_URL=http://localhost:8000` (http/https, no embedded credentials or query string, validated before use).
`DEPLOYED_API_ENV=<label>` names the target (shown in the report header); `prod`/`production` is refused.
Read-only checks always run; tests that POST run only with `DEPLOYED_API_ALLOW_WRITES=1` (use disposable targets).
Run: `pytest -ra -m deployment`.

### OpenAPI contract
`OPENAPI_SPEC_URL=<url or file>` is loaded, parsed (JSON, YAML fallback) and validated; unreachable, non-spec or
invalid documents **fail** rather than skip. `OPENAPI_BASELINE_SPEC=<url or file>` (a trusted earlier spec) enables
breaking-change detection (removed operations/statuses/fields, type changes, new required inputs, newly required auth).
`contracts/practice_api.baseline.json` is a snapshot of this repo's own practice API only (see `contracts/README.md`).
Run: `pytest -ra -m contract`.

### Snowflake and ClickHouse
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` plus `SNOWFLAKE_PASSWORD` or `SNOWFLAKE_PRIVATE_KEY_PATH` (+ optional
warehouse/database/schema/role); `CLICKHOUSE_HOST` (+ port/user/password/database/secure). Partial configuration raises
an error. Queries go through a guard that only permits a single read-only statement (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN).
Use a read-only role. Run: `pytest -ra -m warehouse`.

### API security tests (simulated)
`tests/test_auth_jwt.py` and `tests/test_auth_security.py` (marker `auth`) cover missing/invalid/expired/malformed/
wrong-key/`alg=none` tokens, scopes, roles, spoofing, error-shape and information-leak checks. They run against the
**controlled in-process practice app**, not a real backend. There is no per-user resource endpoint, so
"another user's resources" tests are intentionally not included. Run: `pytest -ra -m auth`.

### GitHub Actions
`.github/workflows/ci.yml`: offline, PostgreSQL service, Docker container, and nightly/manual external jobs. Each job
has a timeout and uploads JUnit XML + HTML reports (`if: always()`). Optional secrets/variables for the external job:
`OPENAPI_SPEC_URL`, `OPENAPI_BASELINE_SPEC`, `DEPLOYED_API_URL`, `DEPLOYED_API_ENV`, `CLICKHOUSE_*`, `SNOWFLAKE_*`
(Settings → Secrets and variables → Actions). No step prints the environment.
