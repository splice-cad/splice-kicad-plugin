"""Tests for the pure-Python helpers in ``ui.action_plugin``.

The wxPython UI surface is not testable outside a real KiCad environment;
only ``_summarize_board`` and config-status formatting are exercised here.
"""

from pathlib import Path

import pytest

from splice_kicad_plugin.config import Config
from splice_kicad_plugin.ui.action_plugin import (
    _build_plan_for_board,
    _connector_summary_line,
    _project_name_for,
    _summarize_board,
)
from splice_kicad_plugin.detect.connectors import ExtractedConnector, ExtractedPin


def test_summarize_board_lists_connectors(tmp_path: Path) -> None:
    board = tmp_path / "smoke.kicad_pcb"
    board.write_text(
        """
        (kicad_pcb (version 20240108) (generator "pcbnew")
          (footprint "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm"
            (property "Reference" "J1")
            (property "Value" "Power")
            (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
            (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
          )
          (footprint "Connector_Generic:Conn_01x04"
            (property "Reference" "J2")
            (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
            (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
            (pad "3" thru_hole circle (at 4 0) (size 1.5 1.5))
            (pad "4" thru_hole circle (at 6 0) (size 1.5 1.5))
          )
          (footprint "Resistor_SMD:R_0402"
            (property "Reference" "R1") (property "Value" "10k"))
        )
        """,
        encoding="utf-8",
    )
    summary = _summarize_board(board)
    assert "v0.0.1" in summary
    assert "20240108" in summary
    assert "Footprints scanned : 3" in summary
    assert "Connectors detected: 2" in summary
    assert "J1" in summary
    assert "J2" in summary
    # Resistor was filtered out
    assert "R1" not in summary
    # Connector metadata extracted from footprint name
    assert "JST" in summary
    assert "PH" in summary
    assert "2.0 mm" in summary
    # Pin counts populated
    assert "2 pins" in summary
    assert "4 pins" in summary


def test_summarize_board_no_connectors(tmp_path: Path) -> None:
    board = tmp_path / "passive_only.kicad_pcb"
    board.write_text(
        """
        (kicad_pcb (version 20240108)
          (footprint "Resistor_SMD:R_0402" (property "Reference" "R1"))
          (footprint "Capacitor_SMD:C_0603" (property "Reference" "C1"))
        )
        """,
        encoding="utf-8",
    )
    summary = _summarize_board(board)
    assert "Footprints scanned : 2" in summary
    assert "Connectors detected: 0" in summary
    assert "no connectors found" in summary


def test_summarize_board_invalid_file(tmp_path: Path) -> None:
    board = tmp_path / "notpcb.kicad_pcb"
    board.write_text('(some_other_form "hi")', encoding="utf-8")
    summary = _summarize_board(board)
    assert "Failed to parse" in summary
    assert "InvalidKicadFileError" in summary


def test_summarize_board_empty_pcb(tmp_path: Path) -> None:
    board = tmp_path / "empty.kicad_pcb"
    board.write_text("(kicad_pcb (version 20240108))", encoding="utf-8")
    summary = _summarize_board(board)
    assert "Footprints scanned : 0" in summary
    assert "Connectors detected: 0" in summary


def test_summarize_board_no_netlist_message(tmp_path: Path) -> None:
    board = tmp_path / "lonely.kicad_pcb"
    board.write_text("(kicad_pcb (version 20240108))", encoding="utf-8")
    summary = _summarize_board(board)
    assert "Netlist:" in summary
    assert "(not found)" in summary
    assert "kicad-cli sch export netlist" in summary


def _two_connector_board(path: Path) -> None:
    path.write_text(
        """
        (kicad_pcb (version 20240108)
          (footprint "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm"
            (property "Reference" "J1") (property "Value" "Power")
            (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
            (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5)))
          (footprint "Connector_Generic:Conn_01x02"
            (property "Reference" "J2") (property "Value" "Output")
            (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
            (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5)))
          (footprint "Resistor_SMD:R_0402"
            (property "Reference" "R1") (property "Value" "10k")))
        """,
        encoding="utf-8",
    )


def test_summarize_with_netlist_populates_pin_functions(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    netlist = tmp_path / "design.net"
    netlist.write_text(
        """
        (export (version "E")
          (components
            (comp (ref "J1")) (comp (ref "J2")) (comp (ref "R1")))
          (nets
            (net (code "1") (name "+5V")
              (node (ref "J1") (pin "1")) (node (ref "J2") (pin "1"))
              (node (ref "R1") (pin "1")))
            (net (code "2") (name "GND")
              (node (ref "J1") (pin "2")) (node (ref "J2") (pin "2"))
              (node (ref "R1") (pin "2")))
            (net (code "3") (name "INTERNAL")
              (node (ref "R1") (pin "1")) (node (ref "R1") (pin "2")))))
        """,
        encoding="utf-8",
    )
    summary = _summarize_board(board)
    # Per-pin function labels appear next to pin numbers.
    assert "Pin 1" in summary
    assert "Pin 2" in summary
    assert "+5V" in summary
    assert "GND" in summary
    # All 4 connector pins (J1.1, J1.2, J2.1, J2.2) got function names.
    assert "Pin functions populated: 4/4" in summary
    # Internal-only net (R1 only) doesn't surface — R1 isn't a connector.
    assert "INTERNAL" not in summary
    # Old per-net endpoint listing removed in favor of per-pin functions.
    assert "Connector-touching nets" not in summary


def test_summarize_with_partial_netlist_shows_nc_for_unconnected(
    tmp_path: Path,
) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    netlist = tmp_path / "design.net"
    # Only J1.1 has a net; J1.2 / J2.1 / J2.2 are absent.
    netlist.write_text(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "VCC")
              (node (ref "J1") (pin "1")))))
        """,
        encoding="utf-8",
    )
    summary = _summarize_board(board)
    assert "Pin functions populated: 1/4" in summary
    # Unconnected pins display 'NC'.
    assert "NC" in summary
    # And no longer the em-dash placeholder.
    assert "—" not in summary


def test_summarize_strips_leading_slash_from_kicad_net_names(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    netlist = tmp_path / "design.net"
    # KiCad-style names with leading slash.
    netlist.write_text(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "/+5V") (node (ref "J1") (pin "1")))
            (net (code "2") (name "/GND") (node (ref "J1") (pin "2")))))
        """,
        encoding="utf-8",
    )
    summary = _summarize_board(board)
    # The displayed function names have the leading slash stripped.
    assert "+5V" in summary
    assert "GND" in summary
    assert "/+5V" not in summary
    assert "/GND" not in summary


# ---------------------------------------------------------------------------
# _build_plan_for_board with selected_refs filtering
# ---------------------------------------------------------------------------


def test_build_plan_for_board_no_filter_includes_all(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    _, connectors, plan = _build_plan_for_board(board)
    refs = {c.reference for c in connectors}
    assert refs == {"J1", "J2"}
    # PlanData has both nodes.
    labels = {n["label"] for n in plan["nodes"].values()}
    assert labels == {"J1", "J2"}


def test_build_plan_for_board_filter_to_subset(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    _, connectors, plan = _build_plan_for_board(board, selected_refs={"J1"})
    assert [c.reference for c in connectors] == ["J1"]
    labels = [n["label"] for n in plan["nodes"].values()]
    assert labels == ["J1"]


def test_build_plan_for_board_filter_to_empty_yields_empty_plan(
    tmp_path: Path,
) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    _, connectors, plan = _build_plan_for_board(board, selected_refs=set())
    assert connectors == []
    assert plan["nodes"] == {}


def test_build_plan_for_board_unknown_ref_in_filter_excludes_silently(
    tmp_path: Path,
) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    _, connectors, plan = _build_plan_for_board(
        board,
        selected_refs={"J1", "J999"},  # J999 doesn't exist
    )
    # Only J1 survives — J999 is silently ignored.
    assert [c.reference for c in connectors] == ["J1"]


# ---------------------------------------------------------------------------
# _connector_summary_line
# ---------------------------------------------------------------------------


def test_connector_summary_line_minimal() -> None:
    c = ExtractedConnector(
        reference="J1", footprint="x", value="",
        pins=[ExtractedPin(number="1"), ExtractedPin(number="2")],
        x=0.0, y=0.0,
    )
    line = _connector_summary_line(c)
    assert line == "J1  (2 pins)"


def test_connector_summary_line_full() -> None:
    c = ExtractedConnector(
        reference="J1", footprint="x", value="",
        pins=[ExtractedPin(number="1")],
        x=0.0, y=0.0,
        manufacturer="JST", series="PH", mpn="S2B-PH-K", pitch_mm=2.0,
    )
    line = _connector_summary_line(c)
    assert "J1" in line and "1 pins" in line
    assert "JST" in line and "PH" in line and "S2B-PH-K" in line
    assert "2.0 mm" in line


# ---------------------------------------------------------------------------
# _project_name_for
# ---------------------------------------------------------------------------


def test_project_name_uses_kicad_pro_when_present(tmp_path: Path) -> None:
    (tmp_path / "my-cool-design.kicad_pro").touch()
    board = tmp_path / "my-cool-design.kicad_pcb"
    board.touch()
    assert _project_name_for(board) == "my-cool-design"


def test_project_name_falls_back_to_board_stem(tmp_path: Path) -> None:
    board = tmp_path / "lonely.kicad_pcb"
    board.touch()
    # No sibling .kicad_pro
    assert _project_name_for(board) == "lonely"


def test_project_name_uses_kicad_pro_even_with_different_name(tmp_path: Path) -> None:
    # Project file may have a different name than the PCB.
    (tmp_path / "my-project.kicad_pro").touch()
    board = tmp_path / "old-pcb-name.kicad_pcb"
    board.touch()
    assert _project_name_for(board) == "my-project"


# ---------------------------------------------------------------------------
# Config-status section
# ---------------------------------------------------------------------------


def test_summarize_with_no_config_says_no_destination(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    summary = _summarize_board(board, Config())  # default → no api key
    # No desktop probe was run, so the helper sees: no key + no desktop.
    assert "Splice CAD destination: NONE AVAILABLE" in summary
    # The summary points the user at how to fix it.
    assert "Splice CAD desktop app" in summary
    assert "API key" in summary


def test_summarize_with_api_key_shows_web_path_ready(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    cfg = Config(api_key="splice_test", base_url="http://localhost:5002")
    summary = _summarize_board(board, cfg)
    assert "Splice CAD destination:" in summary
    assert "http://localhost:5002" in summary
    # Web fallback ready, desktop wasn't probed by _summarize_board.
    assert "API key : configured" in summary
    assert "NONE AVAILABLE" not in summary


def test_summarize_default_config_when_param_omitted(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    summary = _summarize_board(board)
    # No config + no desktop probe — both paths unavailable in _summarize_board.
    assert "NONE AVAILABLE" in summary


# ---------------------------------------------------------------------------
# PlanData payload section
# ---------------------------------------------------------------------------


def test_summarize_includes_plandata_node_and_pin_counts(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    _two_connector_board(board)
    summary = _summarize_board(board)
    # Two connectors, two pins each → 2 nodes, 4 pins.
    assert "PlanData payload:" in summary
    assert "Component nodes: 2" in summary
    assert "Pins           : 4" in summary


def test_summarize_with_invalid_netlist_surfaces_error(tmp_path: Path) -> None:
    board = tmp_path / "design.kicad_pcb"
    board.write_text("(kicad_pcb (version 20240108))", encoding="utf-8")
    netlist = tmp_path / "design.net"
    netlist.write_text("(not_a_valid_netlist)", encoding="utf-8")
    summary = _summarize_board(board)
    assert "Failed to parse" in summary
    assert "NetlistFormatError" in summary
