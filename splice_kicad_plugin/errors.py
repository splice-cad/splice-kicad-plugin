"""Custom exception hierarchy for the Splice KiCad plugin.

Single root means callers can ``except SpliceError`` to catch everything
the plugin raises. See ``docs/RFC-003a-PYTHON-CODEBASE.md`` §2 for usage.
"""

from __future__ import annotations  # PEP 563 — defers `X | None` to strings (Py 3.9 compat)


class SpliceError(Exception):
    """Root of every exception raised by the plugin."""


# Parsing
class ParseError(SpliceError):
    """Generic parse failure."""


class SExprParseError(ParseError):
    """Malformed S-expression input."""

    def __init__(self, line: int | None, message: str) -> None:
        super().__init__(f"S-expression parse error (line {line}): {message}")
        self.line = line


class InvalidKicadFileError(ParseError):
    """KiCad file did not match expected top-level form."""


class NetlistFormatError(ParseError):
    """Malformed KiCad netlist."""


# Detection / build
class ConnectorDetectionError(SpliceError):
    """Failed to load connector-detection patterns."""


class ConductorChainError(SpliceError):
    """Inconsistent input to the conductor-chaining algorithm."""


class PlanBuildError(SpliceError):
    """Assembled PlanData violates a schema invariant."""


# Network / API
class NetworkError(SpliceError):
    """Generic network failure talking to Splice."""


class AuthenticationError(NetworkError):
    """API key invalid, expired, or missing."""


class QuotaExceededError(NetworkError):
    """Splice rate-limited the request."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Quota exceeded; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class PlanTooLargeError(NetworkError):
    """Plan payload exceeded the server's request-size limit."""


class SpliceServerError(NetworkError):
    """Splice returned a non-2xx response."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Splice server error {status}: {body[:200]}")
        self.status = status
        self.body = body


class HandoffError(NetworkError):
    """Both desktop and web handoff failed."""


# Config
class ConfigError(SpliceError):
    """Generic config problem."""


class ConfigLoadError(ConfigError):
    """Could not load plugin config."""


class ConfigSaveError(ConfigError):
    """Could not save plugin config."""


# IPC
class Kicad9IpcUnavailable(SpliceError):
    """KiCad 9.x ``kipy`` IPC is not reachable; caller should fall back to CLI."""


class Kicad9IpcError(SpliceError):
    """KiCad 9.x ``kipy`` IPC raised an error."""
