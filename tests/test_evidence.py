"""Tests for defect-evidence capture and redaction."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from evidence import REDACTED, EvidenceRecorder, redact_body, redact_headers, redact_url

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parent.parent
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.c2lnbmF0dXJl"


def test_sensitive_headers_are_redacted():
    out = redact_headers({"Authorization": f"Bearer {JWT}", "X-Api-Key": "k", "Accept": "application/json"})

    assert out == {"Authorization": REDACTED, "X-Api-Key": REDACTED, "Accept": "application/json"}


def test_json_body_secrets_are_redacted_recursively():
    body = json.dumps({"name": "a", "client_secret": "s3cr3t", "nested": {"access_token": JWT, "ok": 1}})
    out = redact_body(body)

    assert "s3cr3t" not in out and JWT not in out and '"name": "a"' in out


def test_form_body_secrets_are_redacted():
    out = redact_body("grant_type=client_credentials&client_id=reader&client_secret=s3cr3t")

    assert "s3cr3t" not in out and "client_id=reader" in out


def test_free_text_tokens_are_redacted():
    assert JWT not in redact_body(f"failed with token {JWT}")
    assert "abc123" not in redact_body("Bearer abc123 rejected")


def test_url_credentials_and_sensitive_query_values_are_removed():
    out = redact_url("http://user:pw@host:8000/p?token=abc&page=2#frag")

    assert "pw" not in out and "abc" not in out and "page=2" in out and "frag" not in out


def test_long_bodies_are_truncated():
    assert "truncated" in redact_body("x" * 10000)


def test_recorder_captures_in_process_exchange_and_restores_clients(local_api):
    import requests

    original = requests.Session.send
    with EvidenceRecorder().active() as recorder:
        response = local_api.post("/auth/token", data={
            "grant_type": "client_credentials", "client_id": "reader", "client_secret": "wrong"})
        assert requests.Session.send is not original

    assert requests.Session.send is original
    (exchange,) = recorder.exchanges
    assert exchange["status"] == response.status_code == 401
    assert "wrong" not in json.dumps(exchange)


def test_autouse_fixture_records_exchanges_for_this_test(local_api, request):
    local_api.get("/health")

    assert [e["url"].endswith("/health") for e in request.node._evidence.exchanges] == [True]


def test_failed_test_writes_redacted_evidence_file(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(textwrap.dedent(f"""
        def test_fails(local_api):
            local_api.post("/auth/token", data={{"grant_type": "client_credentials",
                "client_id": "reader", "client_secret": "hunter2"}})
            local_api.get("/health", headers={{"Authorization": "Bearer {JWT}"}})
            assert False, "deliberate failure"

        def test_passes(local_api):
            local_api.get("/health")
    """))
    evidence_dir = tmp_path / "evidence"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-p", "conftest", "-p", "no:cacheprovider",
         "--rootdir", str(tmp_path), "-o", "addopts=", "-o", "asyncio_mode=strict"],
        cwd=tmp_path, capture_output=True, text=True,
        env={"PATH": "", "PYTHONPATH": str(REPO), "EVIDENCE_DIR": str(evidence_dir),
             "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(tmp_path)},
    )

    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
    files = list(evidence_dir.glob("*.json"))
    assert len(files) == 1 and "test_fails" in files[0].name
    text = files[0].read_text()
    assert "hunter2" not in text and JWT not in text
    data = json.loads(text)
    assert [e["method"] for e in data["exchanges"]] == ["POST", "GET"]
    assert "deliberate failure" in data["failure"]
