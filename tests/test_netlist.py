"""Tests for ``splice_kicad_plugin.parser.netlist``."""

import pytest

from splice_kicad_plugin.errors import NetlistFormatError
from splice_kicad_plugin.parser.netlist import (
    KicadNet,
    KicadNetlist,
    KicadNetlistComponent,
    KicadNetlistNode,
    parse_kicad_netlist,
)


# Realistic KiCad netlist fragment — two connectors, three nets.
SAMPLE_NETLIST = """
(export (version "E")
  (design (source "/path/to/project.kicad_sch") (date "2026-05-07T22:00:00+0000"))
  (components
    (comp (ref "J1")
      (value "Power Input")
      (footprint "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical")
      (property (name "Manufacturer_Part_Number") (value "S2B-PH-K-S"))
    )
    (comp (ref "J2")
      (value "Power Output")
      (footprint "Connector_Generic:Conn_01x02")
    )
    (comp (ref "R1")
      (value "10k")
      (footprint "Resistor_SMD:R_0402_1005Metric")
    )
  )
  (nets
    (net (code "1") (name "+5V")
      (node (ref "J1") (pin "1") (pinfunction "+5V") (pintype "passive"))
      (node (ref "J2") (pin "1") (pinfunction "+5V") (pintype "passive"))
      (node (ref "R1") (pin "1") (pintype "passive"))
    )
    (net (code "2") (name "GND")
      (node (ref "J1") (pin "2") (pintype "passive"))
      (node (ref "J2") (pin "2") (pintype "passive"))
      (node (ref "R1") (pin "2") (pintype "passive"))
    )
    (net (code "3") (name "Net-(TP1-Pad1)")
      (node (ref "TP1") (pin "1"))
    )
  )
)
"""


# ---------------------------------------------------------------------------
# Top-level form
# ---------------------------------------------------------------------------


def test_rejects_non_export_root() -> None:
    with pytest.raises(NetlistFormatError):
        parse_kicad_netlist('(kicad_pcb (version 20240108))')


def test_rejects_empty_input() -> None:
    with pytest.raises(NetlistFormatError):
        parse_kicad_netlist("")


def test_minimal_export() -> None:
    nl = parse_kicad_netlist('(export (version "E"))')
    assert isinstance(nl, KicadNetlist)
    assert nl.version == "E"
    assert nl.components == ()
    assert nl.nets == ()
    assert dict(nl.nets_by_ref) == {}


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def test_parses_components() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    refs = [c.ref for c in nl.components]
    assert refs == ["J1", "J2", "R1"]
    j1 = nl.components[0]
    assert isinstance(j1, KicadNetlistComponent)
    assert j1.value == "Power Input"
    assert j1.footprint == "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical"
    assert j1.properties["Manufacturer_Part_Number"] == "S2B-PH-K-S"


def test_component_without_ref_is_skipped() -> None:
    src = """
    (export (version "E")
      (components
        (comp (value "10k") (footprint "Resistor_SMD:R_0402"))
        (comp (ref "R1") (value "1k") (footprint "Resistor_SMD:R_0402"))
      )
    )
    """
    nl = parse_kicad_netlist(src)
    assert [c.ref for c in nl.components] == ["R1"]


def test_missing_optional_fields_default_empty() -> None:
    src = """
    (export (version "E")
      (components
        (comp (ref "U1"))
      )
    )
    """
    nl = parse_kicad_netlist(src)
    u1 = nl.components[0]
    assert u1.value == ""
    assert u1.footprint == ""
    assert dict(u1.properties) == {}


# ---------------------------------------------------------------------------
# Nets
# ---------------------------------------------------------------------------


def test_parses_nets() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    assert len(nl.nets) == 3
    names = [n.name for n in nl.nets]
    assert names == ["+5V", "GND", "Net-(TP1-Pad1)"]
    assert nl.nets[0].code == "1"


def test_net_nodes_carry_pin_function_and_type() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    plus_5v = nl.nets[0]
    assert isinstance(plus_5v, KicadNet)
    assert len(plus_5v.nodes) == 3

    j1_pin1 = next(n for n in plus_5v.nodes if n.ref == "J1")
    assert isinstance(j1_pin1, KicadNetlistNode)
    assert j1_pin1.pin == "1"
    assert j1_pin1.pin_function == "+5V"
    assert j1_pin1.pin_type == "passive"

    # R1.1 has no pinfunction
    r1_pin1 = next(n for n in plus_5v.nodes if n.ref == "R1")
    assert r1_pin1.pin_function is None
    assert r1_pin1.pin_type == "passive"


def test_node_without_ref_or_pin_is_skipped() -> None:
    src = """
    (export (version "E")
      (nets
        (net (code "1") (name "VCC")
          (node (ref "J1") (pin "1"))
          (node (pin "2"))           ; missing ref
          (node (ref "J3"))           ; missing pin
        )
      )
    )
    """
    nl = parse_kicad_netlist(src)
    assert [n.ref for n in nl.nets[0].nodes] == ["J1"]


# ---------------------------------------------------------------------------
# nets_by_ref convenience lookup
# ---------------------------------------------------------------------------


def test_nets_by_ref_lookup() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    assert nl.nets_by_ref["J1"]["1"] == "+5V"
    assert nl.nets_by_ref["J1"]["2"] == "GND"
    assert nl.nets_by_ref["J2"]["1"] == "+5V"
    assert nl.nets_by_ref["J2"]["2"] == "GND"
    assert nl.nets_by_ref["R1"]["1"] == "+5V"
    assert nl.nets_by_ref["R1"]["2"] == "GND"


def test_nets_by_ref_missing_pin_raises() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    with pytest.raises(KeyError):
        _ = nl.nets_by_ref["J1"]["999"]


def test_nets_by_ref_missing_ref_raises() -> None:
    nl = parse_kicad_netlist(SAMPLE_NETLIST)
    with pytest.raises(KeyError):
        _ = nl.nets_by_ref["NOPE"]


# ---------------------------------------------------------------------------
# Multiple endpoints across many connectors
# ---------------------------------------------------------------------------


def test_chained_endpoint_net_preserved() -> None:
    """A net connecting J1.3, J7.12, and J9.5 should retain all three nodes
    in order — that's what the conductor chainer (RFC-003b §4) reads."""
    src = """
    (export (version "E")
      (nets
        (net (code "5") (name "/CAN_H")
          (node (ref "J1") (pin "3"))
          (node (ref "J7") (pin "12"))
          (node (ref "J9") (pin "5"))
        )
      )
    )
    """
    nl = parse_kicad_netlist(src)
    can_h = nl.nets[0]
    assert can_h.name == "/CAN_H"
    assert [(n.ref, n.pin) for n in can_h.nodes] == [
        ("J1", "3"),
        ("J7", "12"),
        ("J9", "5"),
    ]
