"""Tests for ``splice_kicad_plugin.client.splice_api``.

Exercises the URL construction, header set, body encoding, and the
HTTPError-to-SpliceError translation. Network calls are mocked at the
``urllib.request.urlopen`` level — no sockets are opened.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
from collections.abc import Mapping
from unittest.mock import MagicMock, patch

import pytest

from splice_kicad_plugin.client.splice_api import (
    SpliceClient,
    WorkingPlanResponse,
)
from splice_kicad_plugin.errors import (
    AuthenticationError,
    NetworkError,
    PlanTooLargeError,
    QuotaExceededError,
    SpliceServerError,
)


def _mock_response(status: int, body: Mapping | None = None) -> MagicMock:
    """Build a fake urlopen() context-manager response."""
    payload = json.dumps(body or {}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = payload
    resp.status = status
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    return resp


def _http_error(
    status: int, body: str = "", retry_after: str | None = None
) -> urllib.error.HTTPError:
    headers: dict = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    err = urllib.error.HTTPError(
        url="http://localhost:5002/api/plans/working",
        code=status,
        msg="error",
        hdrs=headers,  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode("utf-8")),
    )
    return err


# ---------------------------------------------------------------------------
# Auth / config preconditions
# ---------------------------------------------------------------------------


def test_post_without_api_key_raises_auth_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key=None)
    with pytest.raises(AuthenticationError):
        client.post_working_plan({"nodes": {}})


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def test_url_construction_strips_trailing_slash() -> None:
    client = SpliceClient(base_url="http://localhost:5002/", api_key="x")
    assert client._build_url("/api/plans/import") == "http://localhost:5002/api/plans/import"


def test_url_construction_no_trailing_slash() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    assert client._build_url("/api/plans/import") == "http://localhost:5002/api/plans/import"


# ---------------------------------------------------------------------------
# Successful POST
# ---------------------------------------------------------------------------


def test_successful_post_returns_response() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="splice_test")
    plan = {"schemaVersion": 2, "nodes": {}}
    fake_resp = _mock_response(200, {"open_url": "http://localhost:9000/app#/plan"})

    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        result = client.post_working_plan(plan)

    assert isinstance(result, WorkingPlanResponse)
    assert result.open_url == "http://localhost:9000/app#/plan"

    # Inspect the request that was sent.
    called_with = urlopen.call_args
    req = called_with.args[0]
    assert req.full_url == "http://localhost:5002/api/plans/import"
    assert req.get_method() == "POST"
    assert req.headers["Authorization"] == "Bearer splice_test"
    assert req.headers["Content-type"] == "application/json"
    body = json.loads(req.data.decode("utf-8"))
    assert body == {"plan_data": plan}


def test_post_includes_project_id_when_supplied() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan({"nodes": {}}, project_id="abc-123")
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert body["project_id"] == "abc-123"


def test_post_omits_project_id_when_none() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan({"nodes": {}})
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "project_id" not in body


def test_post_includes_project_name_and_description_when_supplied() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan(
            {"nodes": {}},
            project_name="my-cool-design",
            project_description="Imported from KiCad project foo.kicad_pcb",
        )
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert body["project_name"] == "my-cool-design"
    assert body["project_description"] == "Imported from KiCad project foo.kicad_pcb"


def test_post_omits_project_name_when_none() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan({"nodes": {}})
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "project_name" not in body
    assert "project_description" not in body


def test_post_falls_back_open_url_when_server_omits() -> None:
    client = SpliceClient(base_url="https://splice-cad.com", api_key="x")
    fake_resp = _mock_response(200, {})  # no open_url in body
    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = client.post_working_plan({"nodes": {}})
    assert result.open_url == "https://splice-cad.com/app#/plan"


# ---------------------------------------------------------------------------
# Gzip threshold
# ---------------------------------------------------------------------------


def test_post_gzips_large_body() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})

    # A plan body that exceeds 64 KiB after JSON-encoding.
    big_pins = {"pin_" + str(i): {"label": str(i)} for i in range(8000)}
    big_plan = {"nodes": {"comp_x": {"id": "comp_x", "pins": big_pins}}}

    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan(big_plan)

    req = urlopen.call_args.args[0]
    assert req.headers["Content-encoding"] == "gzip"
    # And the bytes actually decompress back to valid JSON.
    decoded = json.loads(gzip.decompress(req.data).decode("utf-8"))
    assert "plan_data" in decoded


def test_post_does_not_gzip_small_body() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        client.post_working_plan({"nodes": {}})
    req = urlopen.call_args.args[0]
    assert "Content-encoding" not in req.headers


# ---------------------------------------------------------------------------
# HTTP error translation
# ---------------------------------------------------------------------------


def test_401_raises_auth_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch("urllib.request.urlopen", side_effect=_http_error(401, "unauthorized")):
        with pytest.raises(AuthenticationError) as e:
            client.post_working_plan({"nodes": {}})
    assert "401" in str(e.value)


def test_413_raises_plan_too_large() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch("urllib.request.urlopen", side_effect=_http_error(413, "too big")):
        with pytest.raises(PlanTooLargeError):
            client.post_working_plan({"nodes": {}})


def test_429_raises_quota_exceeded_with_retry_after() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch(
        "urllib.request.urlopen", side_effect=_http_error(429, "rate limited", retry_after="120")
    ):
        with pytest.raises(QuotaExceededError) as e:
            client.post_working_plan({"nodes": {}})
    assert e.value.retry_after_seconds == 120


def test_429_with_invalid_retry_after_uses_default() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch(
        "urllib.request.urlopen",
        side_effect=_http_error(429, "rate limited", retry_after="not-a-number"),
    ):
        with pytest.raises(QuotaExceededError) as e:
            client.post_working_plan({"nodes": {}})
    assert e.value.retry_after_seconds == 60  # fallback default


def test_500_raises_server_error_with_body() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch("urllib.request.urlopen", side_effect=_http_error(500, "internal explosion")):
        with pytest.raises(SpliceServerError) as e:
            client.post_working_plan({"nodes": {}})
    assert e.value.status == 500
    assert "internal explosion" in e.value.body


def test_url_error_raises_network_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(NetworkError) as e:
            client.post_working_plan({"nodes": {}})
    assert "connection refused" in str(e.value)


def test_timeout_raises_network_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x", timeout_s=1.0)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(NetworkError) as e:
            client.post_working_plan({"nodes": {}})
    assert "1.0s" in str(e.value)


# ---------------------------------------------------------------------------
# test_auth
# ---------------------------------------------------------------------------


def test_test_auth_success() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    fake_resp = _mock_response(200, {"ok": True, "user_id": "abc", "email": "test@example.com"})
    with patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
        result = client.test_auth()
    assert result["ok"] is True
    req = urlopen.call_args.args[0]
    assert req.full_url == "http://localhost:5002/api/plans/import"
    assert req.get_method() == "GET"
    assert req.headers["Authorization"] == "Bearer x"


def test_test_auth_no_key_raises() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key=None)
    with pytest.raises(AuthenticationError):
        client.test_auth()


def test_test_auth_401_raises_auth_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="bad")
    with patch("urllib.request.urlopen", side_effect=_http_error(401, "no")):
        with pytest.raises(AuthenticationError):
            client.test_auth()


def test_test_auth_url_error_raises_network_error() -> None:
    client = SpliceClient(base_url="http://localhost:5002", api_key="x")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(NetworkError):
            client.test_auth()
