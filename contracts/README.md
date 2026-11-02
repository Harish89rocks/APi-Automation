# Contract baseline

`practice_api.baseline.json` is a **snapshot of the practice API's own OpenAPI
document** taken when the file was last regenerated. It is not a published
release and says nothing about any other service. It lets
`tests/test_openapi_contract_extended.py` detect accidental breaking changes
(removed operations/statuses/fields, new required inputs, newly required auth).

After an *intentional* contract change, review the diff and regenerate:

```bash
python -c "import json; from practice_api import app; \
json.dump(app.openapi(), open('contracts/practice_api.baseline.json','w'), indent=2, sort_keys=True)"
```

For a real backend, supply a trusted earlier spec via `OPENAPI_BASELINE_SPEC`
together with `OPENAPI_SPEC_URL`.
