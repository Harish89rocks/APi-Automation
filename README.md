# API Automation Framework

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
