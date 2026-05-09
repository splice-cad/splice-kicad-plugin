"""Tests for ``splice_kicad_plugin.parser.pcb``.

Covers KiCad 6+ (property-based) and KiCad 5 (fp_text-based) forms, missing
fields, malformed input, and numeric parsing edge cases.
"""

import pytest

from splice_kicad_plugin.errors import InvalidKicadFileError
from splice_kicad_plugin.parser.pcb import (
    KicadFootprint,
    KicadPad,
    KicadPcbData,
    parse_kicad_pcb,
)


# ---------------------------------------------------------------------------
# Top-level form
# ---------------------------------------------------------------------------


def test_rejects_non_pcb_root() -> None:
    with pytest.raises(InvalidKicadFileError):
        parse_kicad_pcb('(kicad_sch (version 20240108))')


def test_rejects_empty_input() -> None:
    with pytest.raises(InvalidKicadFileError):
        parse_kicad_pcb("")


def test_minimal_pcb() -> None:
    pcb = parse_kicad_pcb('(kicad_pcb (version 20240108) (generator "pcbnew"))')
    assert isinstance(pcb, KicadPcbData)
    assert pcb.version == "20240108"
    assert pcb.generator == "pcbnew"
    assert pcb.footprints == ()


def test_missing_generator_is_empty_string() -> None:
    pcb = parse_kicad_pcb("(kicad_pcb (version 20240108))")
    assert pcb.version == "20240108"
    assert pcb.generator == ""


# ---------------------------------------------------------------------------
# Footprints — KiCad 6+ (property-based)
# ---------------------------------------------------------------------------


def test_kicad6_footprint_with_properties() -> None:
    src = """
    (kicad_pcb (version 20240108)
      (footprint "Connector_JST:JST_PH_S2B-PH-K"
        (at 100 50 90)
        (property "Reference" "J1")
        (property "Value" "Conn_01x02")
        (property "Footprint" "Connector_JST:JST_PH_S2B-PH-K")
        (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7))
        (pad "2" thru_hole oval (at 2 0) (size 1.7 1.7))
      )
    )
    """
    pcb = parse_kicad_pcb(src)
    assert len(pcb.footprints) == 1
    fp = pcb.footprints[0]
    assert isinstance(fp, KicadFootprint)
    assert fp.reference == "J1"
    assert fp.value == "Conn_01x02"
    assert fp.footprint == "Connector_JST:JST_PH_S2B-PH-K"
    assert fp.x == 100.0
    assert fp.y == 50.0
    assert fp.rotation == 90.0
    assert len(fp.pads) == 2
    assert fp.properties["Reference"] == "J1"
    assert fp.properties["Footprint"] == "Connector_JST:JST_PH_S2B-PH-K"


# ---------------------------------------------------------------------------
# Footprints — KiCad 5 fallback (fp_text-based)
# ---------------------------------------------------------------------------


def test_kicad5_footprint_via_fp_text() -> None:
    src = """
    (kicad_pcb (version 20171130)
      (footprint "Connector_Generic:Conn_01x04"
        (at 50 25)
        (fp_text reference "J5" (at 0 -2))
        (fp_text value "Header_4" (at 0 2))
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    pcb = parse_kicad_pcb(src)
    fp = pcb.footprints[0]
    assert fp.reference == "J5"
    assert fp.value == "Header_4"
    # KiCad 5 has no property block, so the dict is empty.
    assert fp.properties == {}


def test_kicad6_property_takes_precedence_over_fp_text() -> None:
    # If both forms are present (mixed authoring), the property block wins
    # because the parser sets `reference` from properties first.
    src = """
    (kicad_pcb
      (footprint "Mixed"
        (property "Reference" "FROM_PROP")
        (fp_text reference "FROM_FPTEXT" (at 0 0))
      )
    )
    """
    fp = parse_kicad_pcb(src).footprints[0]
    assert fp.reference == "FROM_PROP"


# ---------------------------------------------------------------------------
# Pads
# ---------------------------------------------------------------------------


def test_pad_thru_hole() -> None:
    src = """
    (kicad_pcb
      (footprint "x" (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7))
      )
    )
    """
    pad = parse_kicad_pcb(src).footprints[0].pads[0]
    assert isinstance(pad, KicadPad)
    assert pad.number == "1"
    assert pad.type == "thru_hole"
    assert pad.shape == "circle"
    assert pad.width == 1.7
    assert pad.height == 1.7


def test_pad_smd_with_offset_position() -> None:
    src = """
    (kicad_pcb
      (footprint "x" (property "Reference" "J1")
        (pad "A1" smd rect (at 1.27 -2.54) (size 0.6 1.5))
      )
    )
    """
    pad = parse_kicad_pcb(src).footprints[0].pads[0]
    assert pad.number == "A1"
    assert pad.type == "smd"
    assert pad.shape == "rect"
    assert pad.x == 1.27
    assert pad.y == -2.54


def test_pad_np_thru_hole_preserved() -> None:
    # Mounting holes / non-plated thru-holes should still be parsed; the
    # connector detector filters them out later (kicadParser.ts:973).
    src = """
    (kicad_pcb
      (footprint "x" (property "Reference" "J1")
        (pad "" np_thru_hole circle (at 0 0) (size 3 3))
      )
    )
    """
    pad = parse_kicad_pcb(src).footprints[0].pads[0]
    assert pad.number == ""
    assert pad.type == "np_thru_hole"


def test_malformed_pad_under_4_tokens_is_skipped() -> None:
    src = """
    (kicad_pcb
      (footprint "x" (property "Reference" "J1")
        (pad "1")
        (pad "2" thru_hole circle (at 0 0) (size 1 1))
      )
    )
    """
    fp = parse_kicad_pcb(src).footprints[0]
    # The malformed (pad "1") is silently dropped.
    assert len(fp.pads) == 1
    assert fp.pads[0].number == "2"


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------


def test_non_numeric_position_falls_back_to_zero() -> None:
    # Matches TS `parseFloat(...) || 0` behavior.
    src = """
    (kicad_pcb
      (footprint "x" (property "Reference" "J1")
        (at oops oops)
        (pad "1" thru_hole circle (at 0 0) (size 1 1))
      )
    )
    """
    fp = parse_kicad_pcb(src).footprints[0]
    assert fp.x == 0.0
    assert fp.y == 0.0


# ---------------------------------------------------------------------------
# Multiple footprints + integration
# ---------------------------------------------------------------------------


def test_multiple_footprints_in_order() -> None:
    src = """
    (kicad_pcb (version 20240108)
      (footprint "Resistor_SMD:R_0402" (property "Reference" "R1") (property "Value" "10k"))
      (footprint "Resistor_SMD:R_0402" (property "Reference" "R2") (property "Value" "1k"))
      (footprint "Connector_JST:JST_PH_S2B-PH-K" (property "Reference" "J1") (property "Value" "Power"))
    )
    """
    pcb = parse_kicad_pcb(src)
    refs = [fp.reference for fp in pcb.footprints]
    assert refs == ["R1", "R2", "J1"]


def test_footprint_dataclass_is_frozen() -> None:
    src = '(kicad_pcb (footprint "x" (property "Reference" "J1")))'
    fp = parse_kicad_pcb(src).footprints[0]
    with pytest.raises((AttributeError, Exception)):
        fp.reference = "J2"  # type: ignore[misc]
