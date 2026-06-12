"""KiCad ActionPlugin entry point — preview + Send-to-Splice-CAD flow.

User clicks ``Tools → External Plugins → Export to Splice CAD``. The plugin:

1. Parses the open ``.kicad_pcb`` and any sibling ``.net`` netlist.
2. Extracts connectors and applies pin functions from the netlist.
3. Builds a ``PlanData`` JSON document.
4. Loads ``Config`` (API key + base URL).
5. Shows a preview dialog with stats + connector list.
6. If the user clicks **Send to Splice CAD**, POSTs to ``/api/plans/import``
   and shows the result.

If no API key is configured, the dialog shows preview-only and tells the user
where to put the config file. There's no settings UI yet — hand-edit the JSON.

Outside KiCad (tests, CI), ``pcbnew`` and ``wx`` aren't importable; the guard
at the top makes the pure-Python helpers callable, and the ActionPlugin class
is only defined and registered when KiCad loads us.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import pcbnew  # type: ignore[import-not-found]
    import wx  # type: ignore[import-not-found]
except ImportError:
    pcbnew = None  # type: ignore[assignment]
    wx = None  # type: ignore[assignment]

from ..build.plan import build_plan_data
from ..client.desktop_handoff import (
    DesktopTarget,
    post_to_desktop,
    select_target,
)
from ..client.splice_api import SpliceClient, WorkingPlanResponse
from ..config import Config
from ..detect.connectors import (
    ExtractedConnector,
    apply_netlist,
    extract_connectors_from_pcb,
)
from ..errors import ConfigLoadError, SpliceError
from ..parser.netlist import KicadNetlist, parse_kicad_netlist
from ..parser.pcb import KicadPcbData, parse_kicad_pcb
from ..version import __version__
from .settings_dialog import open_settings_dialog

# ---------------------------------------------------------------------------
# Pure-Python helpers (testable outside KiCad)
# ---------------------------------------------------------------------------


def _summarize_board(board_path: Path, config: Config | None = None) -> str:
    """Parse a .kicad_pcb (and sibling .net if present) and return a preview body.

    If ``config`` is None, uses defaults (which means "not configured" — the
    body shows setup instructions).

    This combines the header summary and the connector pin-detail list into a
    single string. The selectable preview dialog uses the two pieces
    separately (see ``_build_summary_header`` / ``_format_connector_list``).
    """
    text = board_path.read_text(encoding="utf-8")
    try:
        pcb = parse_kicad_pcb(text)
    except Exception as e:
        return f"Failed to parse {board_path}:\n{type(e).__name__}: {e}"

    cfg = config or Config()

    connectors = extract_connectors_from_pcb(pcb)
    netlist, netlist_status = _load_netlist(board_path)
    if netlist is not None and connectors:
        apply_netlist(connectors, netlist)
        annotated = sum(1 for c in connectors for p in c.pins if p.function)
        total = sum(c.pin_count for c in connectors)
        netlist_status += f"\n  Pin functions populated: {annotated}/{total}"

    plan = build_plan_data(connectors, project_name=board_path.stem)

    header = _build_summary_header(board_path, pcb, connectors, netlist_status, plan, cfg)
    if connectors:
        body = _format_connector_list(connectors)
    else:
        body = (
            "(no connectors found — the board has no footprints with "
            "J/CN/CON/P/X prefixes\nor connector-style footprint names)"
        )
    return f"{header}\n\n{body}"


def _build_summary_header(
    board_path: Path,
    pcb,
    connectors: list[ExtractedConnector],
    netlist_status: str,
    plan: dict,
    config: Config,
    *,
    desktop_target: object | None = None,
) -> str:
    """The metadata block (everything *except* the per-connector pin list)."""
    pin_count = sum(len(n["pins"]) for n in plan["nodes"].values())
    sections: list[str] = []
    sections.append(
        f"Splice CAD KiCad plugin v{__version__}\n\n"
        f"Board file: {board_path}\n"
        f"KiCad version field: {pcb.version or 'unknown'}\n"
        f"Footprints scanned : {len(pcb.footprints)}\n"
        f"Connectors detected: {len(connectors)}"
    )
    sections.append(_format_config_status(config, desktop_target=desktop_target))
    sections.append(netlist_status)
    sections.append(
        f"PlanData payload:\n"
        f"  Component nodes: {len(plan['nodes'])}\n"
        f"  Pins           : {pin_count}"
    )
    return "\n\n".join(sections)


def _connector_summary_line(c: ExtractedConnector) -> str:
    """One-line summary of a connector — used inside the CheckListBox."""
    bits: list[str] = [f"{c.reference}  ({c.pin_count} pins)"]
    if c.manufacturer:
        bits.append(c.manufacturer)
    if c.series:
        bits.append(c.series)
    if c.mpn:
        bits.append(c.mpn)
    if c.pitch_mm:
        bits.append(f"{c.pitch_mm} mm")
    return "  |  ".join(bits)


def _format_config_status(cfg: Config, *, desktop_target: object | None = None) -> str:
    """Render the Splice CAD config + desktop handoff state for the preview.

    Two independent send paths:
    - **Desktop**: live if the desktop app is running and reachable. Doesn't
      need an API key — the per-launch secret in the discovery file is the
      auth.
    - **Web**: live if an API key is configured. Used as fallback when the
      desktop isn't running.
    """
    desktop_running = desktop_target is not None
    desktop_line = (
        "  Desktop : running (will receive the plan locally — no API key needed)"
        if desktop_running
        else "  Desktop : not running (web POST will be used)"
    )
    api_line = (
        f"  API key : configured (web POST to {cfg.base_url})"
        if cfg.is_configured
        else "  API key : not set (web fallback unavailable)"
    )
    if desktop_running or cfg.is_configured:
        return f"Splice CAD destination:\n{desktop_line}\n{api_line}"
    return (
        "Splice CAD destination: NONE AVAILABLE\n"
        f"{desktop_line}\n"
        f"{api_line}\n"
        "  Either start the Splice CAD desktop app or set an API key in Settings."
    )


def _format_connector_list(connectors: list[ExtractedConnector]) -> str:
    """Render each connector with its pins and net-derived pin functions."""
    rows: list[str] = []
    for c in connectors:
        bits: list[str] = [f"{c.reference}  ({c.pin_count} pins)"]
        if c.manufacturer:
            bits.append(c.manufacturer)
        if c.series:
            bits.append(c.series)
        if c.mpn:
            bits.append(c.mpn)
        if c.pitch_mm:
            bits.append(f"{c.pitch_mm} mm")
        rows.append("  |  ".join(bits))
        rows.append(f"  {c.footprint}")
        if c.pins:
            pin_num_w = max(len(p.number) for p in c.pins)
            for pin in c.pins:
                fn = pin.function or "NC"
                rows.append(f"    Pin {pin.number:<{pin_num_w}}  {fn}")
        rows.append("")  # spacer
    return "\n".join(rows).rstrip()


def _load_netlist(board_path: Path) -> tuple[KicadNetlist | None, str]:
    """Try to find and parse the project's .net file next to the board."""
    net_path = board_path.with_suffix(".net")
    if not net_path.exists():
        return (
            None,
            f"Netlist: {net_path} (not found)\n"
            "  Pin functions will be empty. Generate one with:\n"
            "    kicad-cli sch export netlist <project>.kicad_sch -o <project>.net",
        )
    try:
        netlist = parse_kicad_netlist(net_path.read_text(encoding="utf-8"))
    except Exception as e:
        return (
            None,
            f"Netlist: {net_path}\n  Failed to parse: {type(e).__name__}: {e}",
        )
    return netlist, f"Netlist: {net_path} ({len(netlist.nets)} nets)"


def _post_with_fallback(
    *,
    plan: dict,
    config: Config,
    project_name: str,
    project_description: str,
) -> WorkingPlanResponse:
    """Try the desktop handoff first, fall back to the web POST.

    Auth paths are independent: desktop uses the per-launch secret from the
    discovery file (no API key required), web uses the configured Bearer
    token. If neither path is available we surface a clear error rather
    than letting the lower-level client raise an opaque AuthenticationError.
    """
    target: DesktopTarget | None = None
    if config.prefer_desktop_when_running:
        try:
            target = select_target()
        except Exception as e:
            print(f"[splice] desktop probe failed: {e}", file=sys.stderr)
            target = None

    if target is not None:
        try:
            return post_to_desktop(
                target,
                plan,
                project_name=project_name,
                project_description=project_description,
            )
        except SpliceError as e:
            # Desktop went away between probe and post (or 4xx/5xx). Fall
            # through to web ONLY if we have an API key — otherwise the
            # web POST will fail with a less-clear message.
            print(
                f"[splice] desktop POST failed, falling back to web: {e}",
                file=sys.stderr,
            )
            if not config.is_configured:
                raise

    if not config.is_configured:
        raise SpliceError(
            "No destination available — start the Splice CAD desktop app, "
            "or set an API key in Settings for the web fallback."
        )

    client = SpliceClient(base_url=config.base_url, api_key=config.api_key)
    return client.post_working_plan(
        plan,
        project_name=project_name,
        project_description=project_description,
    )


def _format_success_body(
    *,
    result: WorkingPlanResponse,
    config: Config,
    project_name: str,
    node_count: int,
    pin_count: int,
    excluded_line: str,
) -> str:
    if result.target == "desktop":
        header = "✓ Plan loaded in Splice CAD desktop"
        server_line = "  Server : (local desktop app — no network roundtrip)\n"
        open_section = ""
    else:
        header = "✓ Plan sent to Splice CAD"
        server_line = f"  Server : {config.base_url}\n"
        open_section = f"\nOpen in Splice CAD:\n  {result.open_url}\n" if result.open_url else ""

    return (
        f"{header}\n\n"
        f"{server_line}"
        f"  Project: {project_name}\n"
        f"  Sent   : {node_count} component nodes, {pin_count} pins\n"
        f"{excluded_line}"
        f"{open_section}"
    )


def _project_name_for(board_path: Path) -> str:
    """Pick a Splice CAD project name based on the KiCad project / board file.

    Prefers the sibling ``.kicad_pro`` filename (the canonical project name)
    over the board filename, since the two diverge sometimes. Falls back to
    the board's stem if no ``.kicad_pro`` is present.
    """
    for sibling in sorted(board_path.parent.glob("*.kicad_pro")):
        return sibling.stem
    return board_path.stem


def _build_plan_for_board(
    board_path: Path,
    selected_refs: set[str] | None = None,
    *,
    fuzzy_property_matching: bool = True,
    prefixes: list[str] | None = None,
) -> tuple[KicadPcbData, list[ExtractedConnector], dict]:
    """Re-do parsing + extraction + plan-build, used by the POST path so we
    don't have to thread the data through the dialog round-trip.

    If ``selected_refs`` is supplied, only connectors whose ``reference`` is
    in that set are included in the resulting PlanData. ``None`` means
    "include everything" (parity with the old single-arg signature).

    ``prefixes`` overrides which reference designators are treated as
    connectors. ``None`` falls back to the canonical default
    (J / CN / CON / P / X from ``shared/kicad-detect.json``).

    ``fuzzy_property_matching`` controls how manufacturer / MPN are pulled
    from KiCad properties — see :func:`extract_connectors_from_pcb`.

    Kept separate from ``_summarize_board`` so the dialog can show a preview
    without committing to the POST path.
    """
    text = board_path.read_text(encoding="utf-8")
    pcb = parse_kicad_pcb(text)
    connectors = extract_connectors_from_pcb(
        pcb,
        prefixes=prefixes,
        fuzzy_property_matching=fuzzy_property_matching,
    )
    netlist, _ = _load_netlist(board_path)
    if netlist is not None and connectors:
        apply_netlist(connectors, netlist, fuzzy_property_matching=fuzzy_property_matching)
    if selected_refs is not None:
        connectors = [c for c in connectors if c.reference in selected_refs]
    plan = build_plan_data(connectors, project_name=board_path.stem)
    return pcb, connectors, plan


# ---------------------------------------------------------------------------
# wxPython-only — preview / result dialogs and the ActionPlugin class
# ---------------------------------------------------------------------------


if pcbnew is not None:

    _MONO_FONT_SIZE = 12

    def _make_text_dialog(title: str, body: str) -> wx.Dialog:
        """Build a resizable, scrollable, monospace dialog. Buttons are added
        by the caller."""
        assert wx is not None
        dlg = wx.Dialog(
            None,
            title=title,
            size=(720, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        text = wx.TextCtrl(
            dlg,
            value=body,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
        )
        text.SetFont(
            wx.Font(
                _MONO_FONT_SIZE,
                wx.FONTFAMILY_TELETYPE,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
            )
        )
        sizer.Add(text, 1, wx.EXPAND | wx.ALL, 8)
        dlg.SetSizer(sizer)
        dlg.SetMinSize((480, 320))
        dlg.CentreOnScreen()
        # Stash the sizer so the caller can append a button row.
        dlg._splice_sizer = sizer  # type: ignore[attr-defined]
        return dlg

    def _show_long_dialog(title: str, body: str) -> None:
        """Single-button dialog (Close)."""
        assert wx is not None
        dlg = _make_text_dialog(title, body)
        btn_sizer = dlg.CreateButtonSizer(wx.OK)
        if btn_sizer is not None:
            dlg._splice_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)  # type: ignore[attr-defined]
        dlg.SetEscapeId(wx.ID_OK)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _show_preview_dialog(title: str, body: str, can_send: bool) -> str:
        """Two-button preview dialog. Returns ``'send'`` or ``'cancel'``.

        Used as a fallback when there are no connectors to choose from
        (everything-or-nothing flow). Most flows use
        ``_show_selectable_preview_dialog`` instead.
        """
        assert wx is not None
        dlg = _make_text_dialog(title, body)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.AddStretchSpacer()
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, "Close")
        btn_row.Add(cancel_btn, 0, wx.RIGHT, 8)
        if can_send:
            send_btn = wx.Button(dlg, wx.ID_OK, "Send to Splice CAD")
            btn_row.Add(send_btn, 0)
            dlg.SetAffirmativeId(wx.ID_OK)
            send_btn.SetDefault()
        dlg.SetEscapeId(wx.ID_CANCEL)
        dlg._splice_sizer.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)  # type: ignore[attr-defined]
        try:
            result = dlg.ShowModal()
        finally:
            dlg.Destroy()
        return "send" if result == wx.ID_OK else "cancel"

    def _show_selectable_preview_dialog(
        title: str,
        header_text: str,
        connectors: list[ExtractedConnector],
        pin_details: str,
        can_send: bool,
    ) -> tuple[str, list[str]]:
        """Preview dialog with a checkable list of connectors.

        Returns ``(action, selected_refs)`` where ``action`` is ``'send'`` or
        ``'cancel'``. ``selected_refs`` is a list (in source order) of
        connector references the user kept checked at submit time. An empty
        list with action='send' is impossible because Send is disabled when
        nothing is checked.
        """
        assert wx is not None

        dlg = wx.Dialog(
            None,
            title=title,
            size=(760, 800),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        mono = wx.Font(
            _MONO_FONT_SIZE,
            wx.FONTFAMILY_TELETYPE,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
        )

        # ---- Header (metadata): fixed-ish height ----
        header_lines = max(8, header_text.count("\n") + 1)
        header_h = min(260, header_lines * 17 + 16)
        header_ctrl = wx.TextCtrl(
            dlg,
            value=header_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
            size=(-1, header_h),
        )
        header_ctrl.SetFont(mono)
        sizer.Add(header_ctrl, 0, wx.EXPAND | wx.ALL, 8)

        # ---- Connector check-list ----
        sel_label_row = wx.BoxSizer(wx.HORIZONTAL)
        sel_label_row.Add(
            wx.StaticText(dlg, label="Connectors to export:"),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        sel_label_row.AddStretchSpacer()
        sel_count_label = wx.StaticText(
            dlg, label=f"{len(connectors)} of {len(connectors)} selected"
        )
        sel_label_row.Add(sel_count_label, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(sel_label_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        items = [_connector_summary_line(c) for c in connectors]
        check_list = wx.CheckListBox(dlg, choices=items, size=(-1, 180))
        check_list.SetFont(mono)
        for i in range(len(connectors)):
            check_list.Check(i, True)
        sizer.Add(check_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        sel_buttons = wx.BoxSizer(wx.HORIZONTAL)
        select_all_btn = wx.Button(dlg, label="Select all")
        deselect_all_btn = wx.Button(dlg, label="Deselect all")
        sel_buttons.Add(select_all_btn, 0, wx.RIGHT, 4)
        sel_buttons.Add(deselect_all_btn, 0)
        sizer.Add(sel_buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ---- Pin details ----
        sizer.Add(
            wx.StaticText(dlg, label="Pin details (all connectors):"),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            8,
        )
        detail_ctrl = wx.TextCtrl(
            dlg,
            value=pin_details,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
        )
        detail_ctrl.SetFont(mono)
        sizer.Add(detail_ctrl, 2, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # ---- Buttons ----
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.AddStretchSpacer()
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, "Close")
        btn_row.Add(cancel_btn, 0, wx.RIGHT, 8)
        send_btn = None
        if can_send:
            send_btn = wx.Button(dlg, wx.ID_OK, f"Send to Splice CAD ({len(connectors)})")
            btn_row.Add(send_btn, 0)
            dlg.SetAffirmativeId(wx.ID_OK)
            send_btn.SetDefault()
        dlg.SetEscapeId(wx.ID_CANCEL)
        sizer.Add(btn_row, 0, wx.EXPAND | wx.ALL, 8)

        dlg.SetSizer(sizer)
        dlg.SetMinSize((520, 600))
        dlg.CentreOnScreen()

        # ---- Selection-change wiring ----
        def update_selection_state() -> None:
            checked = sum(1 for i in range(check_list.GetCount()) if check_list.IsChecked(i))
            sel_count_label.SetLabel(f"{checked} of {len(connectors)} selected")
            if send_btn is not None:
                send_btn.Enable(checked > 0)
                send_btn.SetLabel(f"Send to Splice CAD ({checked})")

        def on_select_all(_evt) -> None:
            for i in range(check_list.GetCount()):
                check_list.Check(i, True)
            update_selection_state()

        def on_deselect_all(_evt) -> None:
            for i in range(check_list.GetCount()):
                check_list.Check(i, False)
            update_selection_state()

        select_all_btn.Bind(wx.EVT_BUTTON, on_select_all)
        deselect_all_btn.Bind(wx.EVT_BUTTON, on_deselect_all)
        check_list.Bind(wx.EVT_CHECKLISTBOX, lambda _evt: update_selection_state())

        try:
            result = dlg.ShowModal()
            if result != wx.ID_OK:
                return "cancel", []
            selected_refs = [
                connectors[i].reference
                for i in range(check_list.GetCount())
                if check_list.IsChecked(i)
            ]
        finally:
            dlg.Destroy()

        return "send", selected_refs

    # Toolbar / menu icon. Path is relative to this module's directory; in
    # both dev (symlinked) and PCM-installed layouts the file lives next to
    # this Python module as ``icon.png``.
    _ICON_PATH = str(Path(__file__).resolve().parent.parent / "icon.png")

    class SpliceExportPlugin(pcbnew.ActionPlugin):
        def defaults(self) -> None:
            self.name = "Export to Splice CAD"
            self.category = "Splice CAD"
            self.description = "Export wired cable-harness plans from KiCad to Splice CAD."
            self.show_toolbar_button = True
            self.icon_file_name = _ICON_PATH

        def Run(self) -> None:  # noqa: N802 — KiCad ActionPlugin API requires this name
            assert wx is not None
            try:
                board = pcbnew.GetBoard()
                board_path = Path(board.GetFileName()) if board else None
                if not board_path or not board_path.exists():
                    wx.MessageBox(
                        "No board file is currently open. Save the project and try again.",
                        "Splice CAD — Export",
                        wx.OK | wx.ICON_WARNING,
                    )
                    return

                try:
                    config = Config.load()
                except ConfigLoadError as e:
                    wx.MessageBox(str(e), "Splice CAD — Export", wx.OK | wx.ICON_ERROR)
                    return

                # Probe desktop FIRST. If desktop is reachable we don't
                # need an API key (desktop handoff uses a per-launch secret
                # from the discovery file). The API key is only required
                # for the web fallback path.
                desktop_target = None
                if config.prefer_desktop_when_running:
                    try:
                        desktop_target = select_target()
                    except Exception:
                        desktop_target = None

                # If neither path is available — desktop not running AND no
                # API key — open settings so the user can pick one.
                if desktop_target is None and not config.is_configured:
                    saved = open_settings_dialog()
                    if not saved:
                        return
                    config = Config.load()
                    if config.prefer_desktop_when_running:
                        try:
                            desktop_target = select_target()
                        except Exception:
                            desktop_target = None
                    if desktop_target is None and not config.is_configured:
                        return

                # Parse + extract once for the preview.
                pcb, connectors, plan = _build_plan_for_board(
                    board_path,
                    fuzzy_property_matching=config.fuzzy_property_matching,
                    prefixes=config.connector_prefixes,
                )
                netlist, netlist_status = _load_netlist(board_path)
                if netlist is not None and connectors:
                    annotated = sum(1 for c in connectors for p in c.pins if p.function)
                    total = sum(c.pin_count for c in connectors)
                    netlist_status += f"\n  Pin functions populated: {annotated}/{total}"

                # If there are no connectors to choose from, fall back to the
                # simple text-only dialog (no point showing an empty checklist).
                if not connectors:
                    body = _summarize_board(board_path, config)
                    _show_preview_dialog(
                        "Splice CAD — Export",
                        body,
                        can_send=False,
                    )
                    return

                header = _build_summary_header(
                    board_path,
                    pcb,
                    connectors,
                    netlist_status,
                    plan,
                    config,
                    desktop_target=desktop_target,
                )
                pin_details = _format_connector_list(connectors)
                # Send is enabled if EITHER auth path works.
                can_send = desktop_target is not None or config.is_configured
                action, selected_refs = _show_selectable_preview_dialog(
                    "Splice CAD — Export",
                    header,
                    connectors,
                    pin_details,
                    can_send=can_send,
                )
                if action != "send" or not selected_refs:
                    return

                # Rebuild the plan with only the selected connectors.
                _, sent_connectors, plan = _build_plan_for_board(
                    board_path,
                    selected_refs=set(selected_refs),
                    fuzzy_property_matching=config.fuzzy_property_matching,
                    prefixes=config.connector_prefixes,
                )

                project_name = _project_name_for(board_path)
                project_description = f"Imported from KiCad project {board_path.name}"

                try:
                    result = _post_with_fallback(
                        plan=plan,
                        config=config,
                        project_name=project_name,
                        project_description=project_description,
                    )
                except SpliceError as e:
                    wx.MessageBox(
                        f"Splice export failed:\n\n{type(e).__name__}: {e}",
                        "Splice CAD — Export",
                        wx.OK | wx.ICON_ERROR,
                    )
                    return

                node_count = len(plan["nodes"])
                pin_count = sum(len(n["pins"]) for n in plan["nodes"].values())
                excluded = len(connectors) - len(sent_connectors)
                excluded_line = f"  Excluded: {excluded} (deselected)\n" if excluded > 0 else ""
                _show_long_dialog(
                    "Splice CAD — Export",
                    _format_success_body(
                        result=result,
                        config=config,
                        project_name=project_name,
                        node_count=node_count,
                        pin_count=pin_count,
                        excluded_line=excluded_line,
                    ),
                )
            except Exception as e:
                wx.MessageBox(
                    f"Splice CAD plugin error: {type(e).__name__}: {e}",
                    "Splice CAD — Export",
                    wx.OK | wx.ICON_ERROR,
                )

    SpliceExportPlugin().register()

    class SpliceSettingsPlugin(pcbnew.ActionPlugin):
        """Settings entry — Tools → External Plugins → Splice CAD — Settings."""

        def defaults(self) -> None:
            self.name = "Splice CAD — Settings"
            self.category = "Splice CAD"
            self.description = "Configure API key and server URL for the Splice CAD plugin."
            self.show_toolbar_button = False
            self.icon_file_name = _ICON_PATH

        def Run(self) -> None:  # noqa: N802 — KiCad ActionPlugin API requires this name
            assert wx is not None
            try:
                open_settings_dialog()
            except Exception as e:
                wx.MessageBox(
                    f"Splice CAD settings error: {type(e).__name__}: {e}",
                    "Splice CAD — Settings",
                    wx.OK | wx.ICON_ERROR,
                )

    SpliceSettingsPlugin().register()
