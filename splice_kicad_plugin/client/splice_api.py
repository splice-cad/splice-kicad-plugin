"""HTTP client for Splice's plan-import endpoint.

Stdlib-only (``urllib.request``) so the plugin works inside KiCad's bundled
Python without pip-installing anything. ``requests`` would be ergonomically
nicer but PCM forbids runtime pip-installs.

Usage::

    client = SpliceClient(base_url="http://localhost:5002", api_key="splice_…")
    result = client.post_working_plan(plan_data, project_id=None)
    print(result.open_url)

Note: targets ``POST /api/plans/import`` (Bearer-authenticated import endpoint)
rather than ``POST /api/plans/working`` (which is session-cookie-only and
designed for the in-app working-plan cache).
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import gzip
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from ..errors import (
    AuthenticationError,
    NetworkError,
    PlanTooLargeError,
    QuotaExceededError,
    SpliceServerError,
)
from ..version import __version__

# Compress the request body when it's larger than this. Most KiCad projects
# fit comfortably under 64 KiB; very large boards may not.
_GZIP_THRESHOLD_BYTES = 64 * 1024


@dataclass(frozen=True)
class WorkingPlanResponse:
    """Result of a successful POST.

    ``target`` records which destination accepted the plan:

    - ``"web"``: posted to the configured Splice backend over HTTPS. ``open_url``
      is a deep-link the caller can open in a browser.
    - ``"desktop"``: posted to the running desktop app's local handoff
      listener. ``open_url`` is the empty string — the plan is already loaded
      in the desktop window.

    ``raw`` carries the parsed JSON body so callers can pull additional fields
    the server may add later.
    """

    open_url: str
    raw: Mapping
    target: str = "web"


@dataclass
class SpliceClient:
    """Tiny client for the working-plan endpoint."""

    base_url: str = "https://splice-cad.com"
    api_key: str | None = None
    timeout_s: float = 30.0
    user_agent: str = f"splice-kicad-plugin/{__version__}"

    def test_auth(self) -> Mapping:
        """Probe ``GET /api/plans/import`` to validate the API key.

        Returns the parsed response body on success (typically
        ``{ok: true, user_id, email}``). Raises:

        - :class:`AuthenticationError` on 401
        - :class:`NetworkError` on connection / timeout errors
        - :class:`SpliceServerError` on other 4xx / 5xx
        """
        if not self.api_key:
            raise AuthenticationError("No API key configured")

        url = self._build_url("/api/plans/import")
        headers: dict = {
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return self._parse_json_response(resp)
        except urllib.error.HTTPError as e:
            self._raise_http_error(e)
            raise  # unreachable; _raise_http_error always raises
        except urllib.error.URLError as e:
            raise NetworkError(f"Failed to reach {self.base_url}: {e.reason}") from e
        except TimeoutError as e:
            raise NetworkError(f"Timed out after {self.timeout_s}s") from e

    def post_working_plan(
        self,
        plan_data: Mapping,
        project_id: UUID | str | None = None,
        project_name: str | None = None,
        project_description: str | None = None,
    ) -> WorkingPlanResponse:
        """POST a PlanData dict to ``{base_url}/api/plans/import``.

        ``project_id`` (when supplied) updates an existing project's plan.
        Otherwise a new project is created using ``project_name`` /
        ``project_description``. The backend defaults to "Imported from
        KiCad" if no name is provided.

        Returns a :class:`WorkingPlanResponse` on success. Raises:

        - :class:`AuthenticationError` on 401
        - :class:`QuotaExceededError` on 429
        - :class:`PlanTooLargeError` on 413
        - :class:`SpliceServerError` on other 4xx / 5xx
        - :class:`NetworkError` on connection / timeout errors
        """
        if not self.api_key:
            raise AuthenticationError("No API key configured — set one in the plugin's config file")

        url = self._build_url("/api/plans/import")
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
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if len(encoded) >= _GZIP_THRESHOLD_BYTES:
            encoded = gzip.compress(encoded)
            headers["Content-Encoding"] = "gzip"

        req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = self._parse_json_response(resp)
        except urllib.error.HTTPError as e:
            self._raise_http_error(e)
        except urllib.error.URLError as e:
            raise NetworkError(f"Failed to reach {self.base_url}: {e.reason}") from e
        except TimeoutError as e:
            raise NetworkError(f"Timed out after {self.timeout_s}s") from e

        return WorkingPlanResponse(
            open_url=str(payload.get("open_url") or self._fallback_open_url()),
            raw=payload,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}{path}"

    def _fallback_open_url(self) -> str:
        # If the server doesn't return an open_url, point at the plan view.
        return f"{self.base_url.rstrip('/')}/app#/plan"

    @staticmethod
    def _parse_json_response(resp) -> dict:
        body = resp.read()
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _raise_http_error(e: urllib.error.HTTPError) -> None:
        """Translate an HTTPError into a typed SpliceError."""
        status = e.code
        try:
            body_bytes = e.read()
            body = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            body = ""

        if status == 401:
            raise AuthenticationError(
                "Splice API rejected the API key (401). Mint a fresh key in the "
                "Account page and update the plugin's config file."
            )
        if status == 413:
            raise PlanTooLargeError(
                f"Plan payload too large for the server (413). Body: {body[:200]}"
            )
        if status == 429:
            retry_after = e.headers.get("Retry-After", "")
            try:
                retry_seconds = int(retry_after)
            except (TypeError, ValueError):
                retry_seconds = 60
            raise QuotaExceededError(retry_seconds)

        raise SpliceServerError(status=status, body=body)
