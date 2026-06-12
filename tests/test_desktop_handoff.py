"""Tests for ``splice_kicad_plugin.client.desktop_handoff``.

The discovery file is read from a path determined by the platform; tests
fake it via ``tmp_path`` + monkey-patching ``_config_dir``. ``urllib.request``
is mocked at the module-import level the same way ``test_splice_api`` does.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from splice_kicad_plugin.client import desktop_handoff
from splice_kicad_plugin.client.desktop_handoff import (
    DesktopTarget,
    post_to_desktop,
    select_target,
)
from splice_kicad_plugin.errors import (
    AuthenticationError,
    NetworkError,
    SpliceServerError,
)

# ---------------------------------------------------------------------------
# Discovery file paths
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect discovery files into a tmp dir."""
    cfg = tmp_path / "com.splice.desktop"
    cfg.mkdir()
    monkeypatch.setattr(desktop_handoff, "_config_dir", lambda: cfg)
    yield cfg


def _write_discovery(
    cfg: Path,
    name: str = "desktop.json",
    *,
    port: int = 51234,
    secret: str = "deadbeef" * 8,
    pid: int | None = None,
    extra: dict | None = None,
) -> Path:
    if pid is None:
        import os

        pid = os.getpid()  # the test process is alive — use that
    data: dict = {
        "port": port,
        "pid": pid,
        "secret": secret,
        "version": "0.1.0-test",
        "protocol": 1,
        "started_at_unix": 1_700_000_000,
    }
    if extra:
        data.update(extra)
    p = cfg / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _mock_health_response(body: dict) -> MagicMock:
    payload = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    return resp


# ---------------------------------------------------------------------------
# _pid_alive
# ---------------------------------------------------------------------------


def test_pid_alive_zero_is_false() -> None:
    assert desktop_handoff._pid_alive(0) is False


def test_pid_alive_negative_is_false() -> None:
    assert desktop_handoff._pid_alive(-1) is False


def test_pid_alive_self_is_true() -> None:
    import os

    assert desktop_handoff._pid_alive(os.getpid()) is True


def test_pid_alive_unlikely_high_is_false() -> None:
    # Pick a PID very unlikely to exist. May rarely flake on busy boxes,
    # but in practice this is a near-zero false-positive rate.
    assert desktop_handoff._pid_alive(987_654) is False


# ---------------------------------------------------------------------------
# select_target — happy + sad paths
# ---------------------------------------------------------------------------


def test_select_target_no_discovery_files(fake_config_dir: Path) -> None:
    assert select_target() is None


def test_select_target_invalid_json_skipped(fake_config_dir: Path) -> None:
    (fake_config_dir / "desktop.json").write_text("{ not json", encoding="utf-8")
    assert select_target() is None


def test_select_target_dead_pid_skipped(fake_config_dir: Path) -> None:
    _write_discovery(fake_config_dir, pid=987_654)  # almost certainly dead
    assert select_target() is None


def test_select_target_health_failure_returns_none(
    fake_config_dir: Path,
) -> None:
    _write_discovery(fake_config_dir)
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        assert select_target() is None


def test_select_target_wrong_service_returns_none(
    fake_config_dir: Path,
) -> None:
    _write_discovery(fake_config_dir)
    fake = _mock_health_response({"service": "something-else", "protocol": 1})
    with patch("urllib.request.urlopen", return_value=fake):
        assert select_target() is None


def test_select_target_unsupported_protocol_returns_none(
    fake_config_dir: Path,
) -> None:
    _write_discovery(fake_config_dir)
    fake = _mock_health_response({"service": "splice-desktop", "protocol": 999, "version": "9.9.9"})
    with patch("urllib.request.urlopen", return_value=fake):
        assert select_target() is None


def test_select_target_happy_path(fake_config_dir: Path) -> None:
    _write_discovery(fake_config_dir, port=51234, secret="secret-hex-zzz")
    fake = _mock_health_response(
        {
            "service": "splice-desktop",
            "protocol": 1,
            "version": "0.1.0-test",
            "ready": True,
        }
    )
    with patch("urllib.request.urlopen", return_value=fake):
        target = select_target()
    assert target is not None
    assert target.base_url == "http://127.0.0.1:51234"
    assert target.secret == "secret-hex-zzz"
    assert target.protocol == 1
    assert target.version == "0.1.0-test"


def test_select_target_dev_file_preferred_over_release(
    fake_config_dir: Path,
) -> None:
    # Both files present — dev should be checked first; we set dev to a dead
    # PID so it gets skipped, but the test verifies the order: probe results
    # tell us which one was picked.
    _write_discovery(fake_config_dir, name="desktop.dev.json", port=11111, secret="dev")
    _write_discovery(fake_config_dir, name="desktop.json", port=22222, secret="release")
    fake = _mock_health_response({"service": "splice-desktop", "protocol": 1, "version": "x"})
    with patch("urllib.request.urlopen", return_value=fake):
        target = select_target()
    assert target is not None
    # Dev file ran first; secret/port match the dev file.
    assert target.secret == "dev"
    assert target.base_url == "http://127.0.0.1:11111"


# ---------------------------------------------------------------------------
# post_to_desktop
# ---------------------------------------------------------------------------


def _http_error(status: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://127.0.0.1:51234/api/plans/import",
        code=status,
        msg="error",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode("utf-8")),
    )


def _target() -> DesktopTarget:
    return DesktopTarget(
        base_url="http://127.0.0.1:51234",
        secret="testsecret",
        version="0.1.0-test",
        protocol=1,
    )


def _ok_response(body: dict) -> MagicMock:
    payload = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = payload
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    return resp


def test_post_to_desktop_success() -> None:
    target = _target()
    fake = _ok_response({"ok": True, "target": "desktop"})
    with patch("urllib.request.urlopen", return_value=fake) as urlopen:
        result = post_to_desktop(
            target,
            {"schemaVersion": 2, "nodes": {}},
            project_name="my-design",
        )

    assert result.target == "desktop"
    assert result.open_url == ""
    assert result.raw == {"ok": True, "target": "desktop"}

    req = urlopen.call_args.args[0]
    assert req.full_url == "http://127.0.0.1:51234/api/plans/import"
    assert req.get_method() == "POST"
    assert req.headers["X-splice-desktop-secret"] == "testsecret"
    assert req.headers["X-splice-source"] == "kicad-plugin"
    body = json.loads(req.data.decode("utf-8"))
    assert body["plan_data"] == {"schemaVersion": 2, "nodes": {}}
    assert body["project_name"] == "my-design"


def test_post_to_desktop_omits_optional_project_fields_when_none() -> None:
    target = _target()
    fake = _ok_response({"ok": True, "target": "desktop"})
    with patch("urllib.request.urlopen", return_value=fake) as urlopen:
        post_to_desktop(target, {"nodes": {}})
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert "project_id" not in body
    assert "project_name" not in body
    assert "project_description" not in body


def test_post_to_desktop_gzips_large_body() -> None:
    target = _target()
    fake = _ok_response({"ok": True})
    big_pins = {"pin_" + str(i): {"label": str(i)} for i in range(8000)}
    big_plan = {"nodes": {"comp_x": {"id": "comp_x", "pins": big_pins}}}

    with patch("urllib.request.urlopen", return_value=fake) as urlopen:
        post_to_desktop(target, big_plan)

    req = urlopen.call_args.args[0]
    assert req.headers["Content-encoding"] == "gzip"
    decoded = json.loads(gzip.decompress(req.data).decode("utf-8"))
    assert "plan_data" in decoded


def test_post_to_desktop_401_raises_auth_error() -> None:
    target = _target()
    with patch("urllib.request.urlopen", side_effect=_http_error(401, "no")):
        with pytest.raises(AuthenticationError):
            post_to_desktop(target, {"nodes": {}})


def test_post_to_desktop_500_raises_server_error() -> None:
    target = _target()
    with patch("urllib.request.urlopen", side_effect=_http_error(500, "internal")):
        with pytest.raises(SpliceServerError) as e:
            post_to_desktop(target, {"nodes": {}})
    assert e.value.status == 500


def test_post_to_desktop_url_error_raises_network_error() -> None:
    target = _target()
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(NetworkError):
            post_to_desktop(target, {"nodes": {}})


def test_post_to_desktop_timeout_raises_network_error() -> None:
    target = _target()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(NetworkError) as e:
            post_to_desktop(target, {"nodes": {}}, timeout_s=2.5)
    assert "2.5s" in str(e.value)
