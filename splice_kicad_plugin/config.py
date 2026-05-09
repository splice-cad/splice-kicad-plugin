"""Plugin configuration — API key + Splice base URL.

Stored as plain JSON at the platform-canonical user-config path:

- macOS:   ``~/Library/Application Support/Splice/kicad-plugin.json``
- Linux:   ``$XDG_CONFIG_HOME/splice/kicad-plugin.json`` (or ``~/.config/…``)
- Windows: ``%APPDATA%\\Splice\\kicad-plugin.json``

The ``SPLICE_KICAD_CONFIG`` env var overrides the path (used for tests, and
when iterating against a non-default install).

Format::

    {
      "api_key": "splice_<uuid>",
      "base_url": "https://splice-cad.com"
    }

There's no settings dialog yet — users hand-edit the file. A wxPython panel is
a future iteration once the local round-trip is solid.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigLoadError, ConfigSaveError

DEFAULT_BASE_URL = "https://splice-cad.com"


def config_path() -> Path:
    """Return the platform-canonical config path, honoring the env override."""
    override = os.environ.get("SPLICE_KICAD_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Splice" / "kicad-plugin.json"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Splice" / "kicad-plugin.json"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "splice" / "kicad-plugin.json"


@dataclass
class Config:
    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    # When True, manufacturer / MPN extraction uses a token-based classifier
    # that catches arbitrary variants ("OEM_Part_No", "Distributor PN", etc.)
    # instead of just the explicit synonym list. Default on — most users
    # benefit. Power users can turn off for stricter / predictable matching.
    fuzzy_property_matching: bool = True

    # When True (default), the plugin checks for a running Splice desktop
    # app via its discovery file and POSTs the plan there directly instead
    # of going to the web backend. Falls back to the web POST if the desktop
    # isn't reachable. Turn off if you always want web.
    prefer_desktop_when_running: bool = True

    # Reference-designator prefixes the plugin treats as connectors. When
    # None (default), the plugin uses the canonical list from
    # ``shared/kicad-detect.json`` (J / CN / CON / P / X). Override per-user
    # if your library uses something else (e.g. add Z for proprietary
    # connector symbols, or restrict to just J).
    connector_prefixes: list[str] | None = None

    @property
    def is_configured(self) -> bool:
        """True if the user has set an API key."""
        return bool(self.api_key)

    @classmethod
    def load(cls) -> "Config":
        """Load config from :func:`config_path` or return defaults if absent.

        Raises :class:`ConfigLoadError` only if the file exists but can't be
        read or parsed; a missing file returns defaults silently.
        """
        path = config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigLoadError(f"Failed to load {path}: {e}") from e
        if not isinstance(data, dict):
            raise ConfigLoadError(f"{path}: expected a JSON object, got {type(data).__name__}")
        # bool() of a missing key is False; pull each out as Optional first
        # so we can default-to-True correctly.
        fuzzy = data.get("fuzzy_property_matching")
        prefer_desktop = data.get("prefer_desktop_when_running")
        prefixes_raw = data.get("connector_prefixes")
        prefixes: list[str] | None
        if isinstance(prefixes_raw, list) and all(isinstance(p, str) for p in prefixes_raw):
            cleaned = [p.strip().upper() for p in prefixes_raw if p.strip()]
            prefixes = cleaned or None
        else:
            prefixes = None
        return cls(
            api_key=data.get("api_key") or None,
            base_url=data.get("base_url") or DEFAULT_BASE_URL,
            fuzzy_property_matching=(
                bool(fuzzy) if fuzzy is not None else True
            ),
            prefer_desktop_when_running=(
                bool(prefer_desktop) if prefer_desktop is not None else True
            ),
            connector_prefixes=prefixes,
        )

    def save(self) -> None:
        """Write config to :func:`config_path` with 0600 perms."""
        path = config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict = {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "fuzzy_property_matching": self.fuzzy_property_matching,
                "prefer_desktop_when_running": self.prefer_desktop_when_running,
            }
            if self.connector_prefixes is not None:
                payload["connector_prefixes"] = list(self.connector_prefixes)
            path.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                path.chmod(0o600)
            except OSError:
                pass  # Windows ACLs differ; ignore
        except OSError as e:
            raise ConfigSaveError(f"Failed to save {path}: {e}") from e
