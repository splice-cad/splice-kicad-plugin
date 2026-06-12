"""Plugin-side dispatch to the Splice desktop app's local handoff listener.

When the desktop app is running it writes a discovery file to its OS-canonical
``app_config_dir``. This module:

1. Locates the discovery file (``desktop.json`` or ``desktop.dev.json``).
2. Verifies the recorded PID is alive.
3. Probes ``GET /api/health`` on the advertised port and checks protocol
   compatibility.
4. POSTs the plan to the listener using ``X-Splice-Desktop-Secret`` auth.

Any failure at steps 1-3 returns ``None`` from :func:`select_target`, signaling
"desktop not reachable — fall back to web". Step 4 raises a typed
``SpliceError`` subclass on failure; the caller decides whether to fall back.

Path resolution matches the desktop's ``tauri::path::app_config_dir()`` output:

- macOS:   ``~/Library/Application Support/com.splice.desktop/<file>``
- Linux:   ``$XDG_CONFIG_HOME/com.splice.desktop/<file>``  (or ``~/.config/...``)
- Windows: ``%APPDATA%\\com.splice.desktop\\<file>``

We prefer the dev file (``desktop.dev.json``) over release (``desktop.json``)
when both exist, matching the desktop's own debug-vs-release split. In
production setups only ``desktop.json`` exists.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import gzip
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..errors import (
    AuthenticationError,
    NetworkError,
    SpliceServerError,
)
from ..version import __version__
from .splice_api import WorkingPlanResponse

_DESKTOP_BUNDLE_ID = "com.splice.desktop"
_FILE_NAMES: tuple[str, ...] = ("desktop.dev.json", "desktop.json")

# Plugin's supported protocol range for the desktop handoff. Bump these in
# lockstep with desktop/src/handoff/PROTOCOL_VERSION when the wire format
# changes incompatibly.
SUPPORTED_PROTOCOL_MIN = 1
SUPPORTED_PROTOCOL_MAX = 1

_GZIP_THRESHOLD_BYTES = 64 * 1024
_DEFAULT_PROBE_TIMEOUT_S = 1.0
_DEFAULT_POST_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class DesktopTarget:
    """Coordinates for posting to a running desktop instance."""

    base_url: str  # ``http://127.0.0.1:<port>``
    secret: str
    version: str
    protocol: int


# ---------------------------------------------------------------------------
# Discovery file
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Resolve the desktop's ``app_config_dir`` for the plugin's bundle id."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _DESKTOP_BUNDLE_ID
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / _DESKTOP_BUNDLE_ID
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / _DESKTOP_BUNDLE_ID


def discovery_paths() -> list[Path]:
    """Candidate discovery file paths, dev-first then release.

    The plugin checks each in order; the first one with a live PID + healthy
    listener wins.
    """
    base = _config_dir()
    return [base / name for name in _FILE_NAMES]


def _read_discovery(path: Path) -> dict | None:
    """Parse a discovery file. Returns ``None`` if missing / unreadable / not
    JSON / not an object."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check via ``os.kill(pid, 0)``."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (different user) — for our
        # purposes that still counts as "running".
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------


def _probe_health(base_url: str, timeout_s: float) -> dict | None:
    """``GET base_url/api/health``. Returns parsed body, or ``None`` on any
    failure (network, timeout, malformed JSON, missing service field)."""
    req = urllib.request.Request(
        f"{base_url}/api/health",
        method="GET",
        headers={"User-Agent": f"splice-kicad-plugin/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("service") != "splice-desktop":
        return None
    return data


# ---------------------------------------------------------------------------
# select_target — top-level "is desktop available?" entry point
# ---------------------------------------------------------------------------


def select_target(
    *,
    probe_timeout_s: float = _DEFAULT_PROBE_TIMEOUT_S,
) -> DesktopTarget | None:
    """Find a running desktop instance, or return None.

    Walks the discovery-file candidates in dev-first order. For each, parses,
    checks PID liveness, probes ``/api/health``, and validates the protocol
    is in our supported range. Returns the first match or ``None``.
    """
    for path in discovery_paths():
        info = _read_discovery(path)
        if info is None:
            continue
        port = info.get("port")
        secret = info.get("secret")
        pid = info.get("pid")
        if not isinstance(port, int) or not isinstance(secret, str) or not secret:
            continue
        if not isinstance(pid, int) or not _pid_alive(pid):
            continue

        base_url = f"http://127.0.0.1:{port}"
        health = _probe_health(base_url, timeout_s=probe_timeout_s)
        if health is None:
            continue
        protocol = health.get("protocol")
        if not isinstance(protocol, int):
            continue
        if not (SUPPORTED_PROTOCOL_MIN <= protocol <= SUPPORTED_PROTOCOL_MAX):
            continue
        version = str(health.get("version") or "")

        return DesktopTarget(
            base_url=base_url,
            secret=secret,
            version=version,
            protocol=protocol,
        )
    return None


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------


def post_to_desktop(
    target: DesktopTarget,
    plan_data: Mapping,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
    timeout_s: float = _DEFAULT_POST_TIMEOUT_S,
) -> WorkingPlanResponse:
    """POST a plan to the desktop handoff listener.

    Body shape mirrors the web ``/api/plans/import`` endpoint so callers can
    use the same payload regardless of target. Auth is via the
    ``X-Splice-Desktop-Secret`` header (per-launch random hex).

    Raises:
    - :class:`AuthenticationError` on 401 (stale secret — desktop restarted
      since we read the discovery file)
    - :class:`SpliceServerError` on other 4xx / 5xx
    - :class:`NetworkError` on connection / timeout errors
    """
    body: dict = {"plan_data": dict(plan_data)}
    if project_id is not None:
        body["project_id"] = str(project_id)
    if project_name is not None:
        body["project_name"] = project_name
    if project_description is not None:
        body["project_description"] = project_description

    encoded = json.dumps(body).encode("utf-8")
    headers: dict = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Splice-Desktop-Secret": target.secret,
        "X-Splice-Source": "kicad-plugin",
        "User-Agent": f"splice-kicad-plugin/{__version__}",
    }
    if len(encoded) >= _GZIP_THRESHOLD_BYTES:
        encoded = gzip.compress(encoded)
        headers["Content-Encoding"] = "gzip"

    req = urllib.request.Request(
        f"{target.base_url}/api/plans/import",
        data=encoded,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        if e.code == 401:
            raise AuthenticationError(
                "Desktop rejected the secret (the discovery file may be stale; "
                "restart the desktop app)."
            ) from e
        raise SpliceServerError(status=e.code, body=err_body) from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach desktop at {target.base_url}: {e.reason}") from e
    except TimeoutError as e:
        raise NetworkError(f"Timed out reaching desktop after {timeout_s}s") from e

    return WorkingPlanResponse(
        target="desktop",
        open_url="",  # plan is already loaded in the running app
        raw=payload,
    )


__all__ = [
    "SUPPORTED_PROTOCOL_MAX",
    "SUPPORTED_PROTOCOL_MIN",
    "DesktopTarget",
    "discovery_paths",
    "post_to_desktop",
    "select_target",
]
