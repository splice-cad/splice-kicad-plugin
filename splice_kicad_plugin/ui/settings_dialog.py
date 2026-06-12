"""Settings dialog — paste API key and server URL.

The user opens this from ``Tools → External Plugins → Splice — Settings``,
or it auto-opens the first time they hit ``Export to Splice`` without a
configured API key.

Outside KiCad (tests, CI), ``wx`` isn't importable; the dialog class is
gated, but ``validate_config`` is pure-Python and tested.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import re
import webbrowser

try:
    import wx  # type: ignore[import-not-found]
except ImportError:
    wx = None  # type: ignore[assignment]

from ..client.splice_api import SpliceClient
from ..config import DEFAULT_BASE_URL, Config, config_path
from ..detect.patterns import DEFAULT_CONNECTOR_PREFIXES
from ..errors import (
    AuthenticationError,
    ConfigSaveError,
    NetworkError,
    SpliceError,
)

_API_KEY_RE = re.compile(r"^splice_[A-Za-z0-9_-]{8,}$")
_GET_API_KEY_URL = "https://splice-cad.com/app#/account"
_PREFIX_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_prefixes(text: str) -> list[str] | None:
    """Parse a comma-separated list of designator prefixes from settings input.

    Returns ``None`` when the input is blank — the caller falls back to the
    canonical default list. Empty / whitespace tokens are ignored. Each
    surviving token is upper-cased; a non-empty result list is returned only
    if every token validates as ``[A-Z][A-Z0-9_]*``.
    """
    if not text or not text.strip():
        return None
    tokens = [t.strip().upper() for t in text.split(",") if t.strip()]
    if not tokens:
        return None
    for t in tokens:
        if not _PREFIX_TOKEN_RE.match(t):
            return None
    return tokens


def format_prefixes(prefixes: list[str] | None) -> str:
    """Inverse of :func:`parse_prefixes` for display in the settings field."""
    if not prefixes:
        return ""
    return ", ".join(prefixes)


def validate_config(
    api_key: str,
    base_url: str,
    *,
    prefixes_text: str = "",
) -> tuple[bool, str | None]:
    """Validate field values. Returns ``(is_valid, error_message_or_None)``.

    The API key is **optional** — the plugin can deliver plans to a running
    Splice CAD desktop app over its local handoff listener (no Bearer token
    required, just the per-launch secret in the discovery file). The web
    fallback path needs the API key, but if the user only ever uses desktop
    they can save the dialog with the field blank.
    """
    if api_key and not _API_KEY_RE.match(api_key):
        return False, "API key should start with 'splice_' followed by your token."
    if not base_url:
        return False, "Server URL is required."
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return False, "Server URL must start with http:// or https://"
    # Prefixes are optional (blank → use defaults). If supplied, every token
    # must look like a designator prefix: uppercase letter, optional more
    # uppercase / digits / underscores.
    if prefixes_text.strip() and parse_prefixes(prefixes_text) is None:
        return (
            False,
            "Connector prefixes must be comma-separated and start with a letter "
            "(e.g. 'J, CN, CON, P, X').",
        )
    return True, None


if wx is not None:

    _COLOR_OK = wx.Colour(0, 130, 0)
    _COLOR_ERR = wx.Colour(180, 0, 0)
    _COLOR_WARN = wx.Colour(180, 100, 0)
    _COLOR_HINT = wx.Colour(120, 120, 120)
    _COLOR_INFO = wx.Colour(60, 60, 60)

    class SpliceSettingsDialog(wx.Dialog):
        """Modal settings dialog. Loads the current ``Config``, lets the user
        edit it, validates + saves on OK."""

        def __init__(self, parent=None) -> None:
            super().__init__(
                parent,
                title="Splice CAD — Settings",
                size=(580, 740),
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            )
            self._cfg = Config.load()
            self._build_ui()
            self.SetMinSize((520, 680))
            self.CentreOnScreen()

        # --- UI construction -------------------------------------------

        def _build_ui(self) -> None:
            sizer = wx.BoxSizer(wx.VERTICAL)

            heading = wx.StaticText(
                self,
                label=(
                    "Connect this plugin to your Splice CAD account.\n"
                    "Paste an API key from your Splice CAD account page."
                ),
            )
            sizer.Add(heading, 0, wx.ALL, 12)

            # API key
            sizer.Add(
                wx.StaticText(self, label="API key (optional if using desktop)"),
                0,
                wx.LEFT | wx.RIGHT,
                12,
            )
            api_row = wx.BoxSizer(wx.HORIZONTAL)
            self._api_field = wx.TextCtrl(
                self,
                value=self._cfg.api_key or "",
                style=wx.TE_PASSWORD,
            )
            api_row.Add(self._api_field, 1, wx.RIGHT, 4)
            self._show_btn = wx.ToggleButton(self, label="Show")
            self._show_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_toggle_show)
            api_row.Add(self._show_btn, 0)
            sizer.Add(api_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            link_btn = wx.Button(self, label="Get API key on splice-cad.com…")
            link_btn.Bind(wx.EVT_BUTTON, lambda evt: webbrowser.open(_GET_API_KEY_URL))
            sizer.Add(link_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Server URL
            sizer.Add(wx.StaticText(self, label="Server URL"), 0, wx.LEFT | wx.RIGHT, 12)
            self._url_field = wx.TextCtrl(self, value=self._cfg.base_url)
            sizer.Add(self._url_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
            url_hint = wx.StaticText(
                self,
                label=f"Default: {DEFAULT_BASE_URL}. Override for local testing.",
            )
            url_hint.SetForegroundColour(_COLOR_HINT)
            sizer.Add(url_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Fuzzy property matching toggle
            self._fuzzy_box = wx.CheckBox(
                self,
                label="Fuzzy match KiCad properties for manufacturer / MPN",
            )
            self._fuzzy_box.SetValue(self._cfg.fuzzy_property_matching)
            sizer.Add(self._fuzzy_box, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            fuzzy_hint = wx.StaticText(
                self,
                label=(
                    "When on: tokens like 'manufacturer', 'mfr', 'part number' in "
                    "ANY field name are recognized\n(e.g. OEM_Part_Number, "
                    "Distributor_Manufacturer). When off: only the explicit "
                    "synonym list."
                ),
            )
            fuzzy_hint.SetForegroundColour(_COLOR_HINT)
            sizer.Add(fuzzy_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Connector designator prefixes
            sizer.Add(
                wx.StaticText(self, label="Connector designator prefixes"),
                0,
                wx.LEFT | wx.RIGHT | wx.TOP,
                12,
            )
            self._prefixes_field = wx.TextCtrl(
                self,
                value=format_prefixes(self._cfg.connector_prefixes),
            )
            sizer.Add(self._prefixes_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
            prefixes_hint = wx.StaticText(
                self,
                label=(
                    "Comma-separated, e.g. 'J, CN, CON, P, X'. Blank uses "
                    "the canonical default\n"
                    f"({', '.join(DEFAULT_CONNECTOR_PREFIXES)}). "
                    "Add custom prefixes if your symbol library uses others."
                ),
            )
            prefixes_hint.SetForegroundColour(_COLOR_HINT)
            sizer.Add(prefixes_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Prefer-desktop toggle
            self._desktop_box = wx.CheckBox(
                self,
                label="Send to Splice CAD desktop app when it's running",
            )
            self._desktop_box.SetValue(self._cfg.prefer_desktop_when_running)
            sizer.Add(self._desktop_box, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            desktop_hint = wx.StaticText(
                self,
                label=(
                    "When on: if Splice CAD desktop is running, the plugin POSTs the "
                    "plan straight to it over\nlocalhost (no network roundtrip, "
                    "works offline). Falls back to the server URL above if\n"
                    "desktop isn't reachable."
                ),
            )
            desktop_hint.SetForegroundColour(_COLOR_HINT)
            sizer.Add(desktop_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Test connection
            test_row = wx.BoxSizer(wx.HORIZONTAL)
            self._test_btn = wx.Button(self, label="Test connection")
            self._test_btn.Bind(wx.EVT_BUTTON, self._on_test)
            test_row.Add(self._test_btn, 0, wx.RIGHT, 8)
            self._status = wx.StaticText(self, label="")
            test_row.Add(self._status, 1, wx.ALIGN_CENTER_VERTICAL)
            sizer.Add(test_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # Path hint
            path_hint = wx.StaticText(
                self,
                label=f"Saved to: {config_path()}",
            )
            path_hint.SetForegroundColour(_COLOR_HINT)
            sizer.Add(path_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            # OK / Cancel buttons
            btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
            ok_btn = self.FindWindowById(wx.ID_OK, self)
            if ok_btn is not None:
                ok_btn.SetLabel("Save")
            sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            self.SetSizer(sizer)

        # --- Event handlers --------------------------------------------

        def _on_toggle_show(self, evt) -> None:
            """macOS / GTK don't allow toggling TE_PASSWORD live, so we
            recreate the TextCtrl with the new style."""
            assert wx is not None
            current_value = self._api_field.GetValue()
            old = self._api_field
            new_style = (
                old.GetWindowStyleFlag() & ~wx.TE_PASSWORD
                if self._show_btn.GetValue()
                else old.GetWindowStyleFlag() | wx.TE_PASSWORD
            )
            new_field = wx.TextCtrl(self, value=current_value, style=new_style)

            # Swap into the same sizer slot.
            sizer = old.GetContainingSizer()
            sizer.Replace(old, new_field, recursive=True)
            old.Destroy()
            self._api_field = new_field
            self.Layout()

        def _on_test(self, evt) -> None:
            assert wx is not None
            api_key = self._api_field.GetValue().strip()
            base_url = self._url_field.GetValue().strip()
            prefixes_text = self._prefixes_field.GetValue().strip()
            if not api_key:
                self._set_status(
                    "Enter an API key first — Test only checks the web auth path.",
                    _COLOR_HINT,
                )
                return
            valid, err = validate_config(api_key, base_url, prefixes_text=prefixes_text)
            if not valid:
                self._set_status(f"⚠ {err}", _COLOR_WARN)
                return

            self._test_btn.Disable()
            self._set_status("Testing…", _COLOR_INFO)
            wx.Yield()
            try:
                client = SpliceClient(base_url=base_url, api_key=api_key, timeout_s=8.0)
                client.test_auth()
                self._set_status("✓ Connected — API key is valid.", _COLOR_OK)
            except AuthenticationError:
                self._set_status("✗ Auth rejected (401). Check the key.", _COLOR_ERR)
            except NetworkError as e:
                self._set_status(f"✗ Cannot reach {base_url}\n  {e}", _COLOR_ERR)
            except SpliceError as e:
                self._set_status(f"✗ {type(e).__name__}: {e}", _COLOR_ERR)
            finally:
                self._test_btn.Enable()

        def _set_status(self, text: str, color) -> None:
            self._status.SetLabel(text)
            self._status.SetForegroundColour(color)
            self._status.Refresh()

        # --- Result extraction -----------------------------------------

        def get_config(self) -> Config:
            return Config(
                api_key=self._api_field.GetValue().strip() or None,
                base_url=self._url_field.GetValue().strip() or DEFAULT_BASE_URL,
                fuzzy_property_matching=self._fuzzy_box.GetValue(),
                prefer_desktop_when_running=self._desktop_box.GetValue(),
                connector_prefixes=parse_prefixes(self._prefixes_field.GetValue()),
            )


def open_settings_dialog() -> bool:
    """Show the settings dialog modally; save on OK.

    Returns True iff the user clicked Save AND the new config validates AND
    the save succeeded. Otherwise False (user canceled / validation failed /
    save failed).
    """
    if wx is None:
        return False

    dlg = SpliceSettingsDialog()
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return False
        new_config = dlg.get_config()
    finally:
        dlg.Destroy()

    valid, err = validate_config(
        new_config.api_key or "",
        new_config.base_url,
        prefixes_text=format_prefixes(new_config.connector_prefixes),
    )
    if not valid:
        wx.MessageBox(
            f"Settings not saved — {err}",
            "Splice CAD — Settings",
            wx.OK | wx.ICON_WARNING,
        )
        return False

    try:
        new_config.save()
    except ConfigSaveError as e:
        wx.MessageBox(
            f"Failed to save settings:\n\n{e}",
            "Splice CAD — Settings",
            wx.OK | wx.ICON_ERROR,
        )
        return False

    wx.MessageBox(
        f"Settings saved to:\n{config_path()}",
        "Splice CAD — Settings",
        wx.OK | wx.ICON_INFORMATION,
    )
    return True
