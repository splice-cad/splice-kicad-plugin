"""Tests for ``splice_kicad_plugin.detect.connectors``."""

from splice_kicad_plugin.detect.connectors import (
    ExtractedConnector,
    ExtractedPin,
    apply_netlist,
    extract_connectors_from_pcb,
    is_connector_footprint,
)
from splice_kicad_plugin.parser.netlist import (
    KicadNet,
    KicadNetlist,
    KicadNetlistNode,
    parse_kicad_netlist,
)
from splice_kicad_plugin.parser.pcb import (
    KicadFootprint,
    KicadPad,
    KicadPcbData,
    parse_kicad_pcb,
)


def _fp(ref: str, footprint: str = "Connector_Generic:Conn_01x04", pads: int = 0) -> KicadFootprint:
    return KicadFootprint(
        reference=ref,
        footprint=footprint,
        value="",
        x=0.0, y=0.0, rotation=0.0,
        pads=tuple(
            KicadPad(number=str(i + 1), type="thru_hole", shape="circle",
                     x=0.0, y=0.0, width=1.5, height=1.5)
            for i in range(pads)
        ),
        properties={},
    )


# ---------------------------------------------------------------------------
# is_connector_footprint
# ---------------------------------------------------------------------------


def test_detect_by_reference_prefix() -> None:
    assert is_connector_footprint(_fp("J1"))
    assert is_connector_footprint(_fp("CN3"))
    assert is_connector_footprint(_fp("CON7"))
    assert is_connector_footprint(_fp("P12"))
    assert is_connector_footprint(_fp("X9"))


def test_reject_non_connector_references() -> None:
    # Resistors, caps, ICs, mounting holes — none match the prefix.
    assert not is_connector_footprint(_fp("R1", "Resistor_SMD:R_0402"))
    assert not is_connector_footprint(_fp("C12", "Capacitor_SMD:C_0603"))
    assert not is_connector_footprint(_fp("U2", "Package_SO:SOIC-8"))
    assert not is_connector_footprint(_fp("MH1", "MountingHole_3.2mm"))


def test_detect_by_footprint_name_when_ref_doesnt_match() -> None:
    # An odd reference but a connector-shaped footprint name still matches.
    assert is_connector_footprint(_fp("U99", "Connector_JST:JST_PH_S2B"))
    assert is_connector_footprint(_fp("Z1", "Molex_PicoBlade_53261-1290"))
    assert is_connector_footprint(_fp("X0", "Pin_Header_Straight_1x4"))


def test_custom_prefix_override() -> None:
    # Some shops use unusual prefixes. The override path lets users opt in.
    assert is_connector_footprint(_fp("Z1", "MyOwnConnector"), prefixes=("Z",))
    assert not is_connector_footprint(_fp("J1", "Resistor_SMD:R"), prefixes=("Z",))


# ---------------------------------------------------------------------------
# extract_connectors_from_pcb
# ---------------------------------------------------------------------------


def test_extract_filters_to_connectors_only() -> None:
    src = """
    (kicad_pcb (version 20240108)
      (footprint "Resistor_SMD:R_0402" (property "Reference" "R1"))
      (footprint "Connector_JST:JST_PH_S2B-PH-K"
        (property "Reference" "J1") (property "Value" "Power")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
        (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
      )
      (footprint "Capacitor_SMD:C_0603" (property "Reference" "C5"))
      (footprint "Connector_Generic:Conn_01x04"
        (property "Reference" "J2")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
        (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
        (pad "3" thru_hole circle (at 4 0) (size 1.5 1.5))
        (pad "4" thru_hole circle (at 6 0) (size 1.5 1.5))
      )
      (footprint "MountingHole_3.2mm" (property "Reference" "H1"))
    )
    """
    pcb = parse_kicad_pcb(src)
    conns = extract_connectors_from_pcb(pcb)
    refs = [c.reference for c in conns]
    assert refs == ["J1", "J2"]


def test_extract_signal_pad_count_drops_mounting_holes() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_Generic:Conn_01x04"
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
        (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
        (pad "MP1" np_thru_hole circle (at 5 0) (size 3 3))
        (pad "" np_thru_hole circle (at -5 0) (size 3 3))
        (pad "MH1" thru_hole circle (at 7 0) (size 3 3))
      )
    )
    """
    pcb = parse_kicad_pcb(src)
    conn = extract_connectors_from_pcb(pcb)[0]
    # Only 2 signal pads — the np_thru_holes and MP/MH-prefixed pads are excluded.
    assert conn.pin_count == 2
    assert [p.number for p in conn.pins] == ["1", "2"]


def test_extract_natural_sort_order() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_Generic:Conn_01x02" (property "Reference" "J10")
        (pad "1" thru_hole circle (at 0 0) (size 1 1)))
      (footprint "Connector_Generic:Conn_01x02" (property "Reference" "J2")
        (pad "1" thru_hole circle (at 0 0) (size 1 1)))
      (footprint "Connector_Generic:Conn_01x02" (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1 1)))
    )
    """
    pcb = parse_kicad_pcb(src)
    refs = [c.reference for c in extract_connectors_from_pcb(pcb)]
    assert refs == ["J1", "J2", "J10"]


def test_extract_enhances_metadata_from_footprint_name() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
        (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
        (pad "3" thru_hole circle (at 4 0) (size 1.5 1.5))
        (pad "4" thru_hole circle (at 6 0) (size 1.5 1.5))
      )
    )
    """
    pcb = parse_kicad_pcb(src)
    conn = extract_connectors_from_pcb(pcb)[0]
    assert conn.manufacturer == "JST"
    assert conn.series == "XH"
    assert conn.pitch_mm == 2.5
    assert conn.mpn == "B4B-XH-A"
    assert conn.mounting_style == "Vertical"
    assert conn.pin_count == 4


def test_extract_enhance_disabled() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm"
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    pcb = parse_kicad_pcb(src)
    conn = extract_connectors_from_pcb(pcb, enhance=False)[0]
    # No metadata extraction performed.
    assert conn.manufacturer is None
    assert conn.series is None
    assert conn.mpn is None


def test_extract_empty_pcb() -> None:
    pcb = KicadPcbData(version="", generator="", footprints=())
    assert extract_connectors_from_pcb(pcb) == []


def test_extract_no_connectors_only_passives() -> None:
    src = """
    (kicad_pcb
      (footprint "Resistor_SMD:R_0402" (property "Reference" "R1"))
      (footprint "Capacitor_SMD:C_0603" (property "Reference" "C1"))
    )
    """
    assert extract_connectors_from_pcb(parse_kicad_pcb(src)) == []


def test_extract_pins_start_without_function() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_JST:JST_PH_S2B-PH-K"
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
        (pad "2" thru_hole circle (at 2 0) (size 1.5 1.5))
      )
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert all(isinstance(p, ExtractedPin) for p in conn.pins)
    assert all(p.function is None for p in conn.pins)


# ---------------------------------------------------------------------------
# apply_netlist
# ---------------------------------------------------------------------------


def _two_connector_pcb() -> KicadPcbData:
    src = """
    (kicad_pcb
      (footprint "Connector_JST:JST_PH_S2B-PH-K"
        (property "Reference" "J1")
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
    )
    """
    return parse_kicad_pcb(src)


def test_apply_netlist_sets_pin_functions_from_net_names() -> None:
    pcb = _two_connector_pcb()
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "+5V")
              (node (ref "J1") (pin "1"))
              (node (ref "J2") (pin "1")))
            (net (code "2") (name "GND")
              (node (ref "J1") (pin "2"))
              (node (ref "J2") (pin "2")))
            (net (code "3") (name "CAN_H")
              (node (ref "J2") (pin "3")))
            (net (code "4") (name "CAN_L")
              (node (ref "J2") (pin "4")))
          )
        )
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)

    j1 = next(c for c in connectors if c.reference == "J1")
    assert [p.function for p in j1.pins] == ["+5V", "GND"]

    j2 = next(c for c in connectors if c.reference == "J2")
    assert [p.function for p in j2.pins] == ["+5V", "GND", "CAN_H", "CAN_L"]


def test_apply_netlist_pin_without_net_keeps_function_none() -> None:
    pcb = _two_connector_pcb()
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "VCC") (node (ref "J1") (pin "1")))
          )
        )
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    j1 = next(c for c in connectors if c.reference == "J1")
    assert j1.pins[0].function == "VCC"
    assert j1.pins[1].function is None  # pin 2 not in netlist


def test_apply_netlist_connector_not_in_netlist() -> None:
    pcb = _two_connector_pcb()
    netlist = parse_kicad_netlist(
        '(export (version "E") (nets))'  # empty netlist
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    # All pins on all connectors stay function=None
    for conn in connectors:
        assert all(p.function is None for p in conn.pins)


def test_apply_netlist_is_idempotent() -> None:
    pcb = _two_connector_pcb()
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "+5V") (node (ref "J1") (pin "1")))
          )
        )
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    apply_netlist(connectors, netlist)  # second call should be a no-op
    j1 = next(c for c in connectors if c.reference == "J1")
    assert j1.pins[0].function == "+5V"


# ---------------------------------------------------------------------------
# normalize_net_name + leading-slash handling
# ---------------------------------------------------------------------------


def test_apply_netlist_strips_kicad_root_slash() -> None:
    pcb = _two_connector_pcb()
    # KiCad emits leading slashes on every net even at root scope.
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "/+5V") (node (ref "J1") (pin "1")))
            (net (code "2") (name "/GND") (node (ref "J1") (pin "2")))
          )
        )
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    j1 = next(c for c in connectors if c.reference == "J1")
    # Leading slashes stripped; what's stored is the user-facing name.
    assert j1.pins[0].function == "+5V"
    assert j1.pins[1].function == "GND"


def test_apply_netlist_preserves_internal_hierarchy_slashes() -> None:
    pcb = _two_connector_pcb()
    # Hierarchical names like /CAN/CAN_H keep the inner slash.
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (nets
            (net (code "1") (name "/CAN/CAN_H") (node (ref "J1") (pin "1")))
            (net (code "2") (name "/Power/+5V") (node (ref "J1") (pin "2")))
          )
        )
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    j1 = next(c for c in connectors if c.reference == "J1")
    assert j1.pins[0].function == "CAN/CAN_H"
    assert j1.pins[1].function == "Power/+5V"


def test_normalize_net_name_function() -> None:
    from splice_kicad_plugin.detect.connectors import normalize_net_name
    assert normalize_net_name("/+5V") == "+5V"
    assert normalize_net_name("/CAN/CAN_H") == "CAN/CAN_H"
    assert normalize_net_name("VCC") == "VCC"  # no leading slash, untouched
    assert normalize_net_name("") == ""


# ---------------------------------------------------------------------------
# Manufacturer / MPN pull-through from properties
# ---------------------------------------------------------------------------


def test_extract_pulls_mpn_and_mfr_from_pcb_properties() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_Generic:Conn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer" "Wago")
        (property "Manufacturer_Part_Number" "236-402")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    # PCB property values win over footprint-name parsing.
    assert conn.manufacturer == "Wago"
    assert conn.mpn == "236-402"


def test_extract_property_synonyms() -> None:
    src = """
    (kicad_pcb
      (footprint "Connector_Generic:Conn_01x02"
        (property "Reference" "J1")
        (property "Mfr" "Phoenix Contact")
        (property "MPN" "1985083")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.manufacturer == "Phoenix Contact"
    assert conn.mpn == "1985083"


def test_extract_pcb_property_beats_footprint_name() -> None:
    # JST in the footprint name would otherwise set manufacturer="JST",
    # but the PCB property says Hirose — explicit wins.
    src = """
    (kicad_pcb
      (footprint "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm"
        (property "Reference" "J1")
        (property "Manufacturer" "Hirose")
        (property "Manufacturer_Part_Number" "DF13-2P-1.25DSA")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.manufacturer == "Hirose"
    assert conn.mpn == "DF13-2P-1.25DSA"


def test_apply_netlist_pulls_mpn_and_mfr_from_netlist_props() -> None:
    # PCB has no property fields — netlist does. apply_netlist fills them.
    src = """
    (kicad_pcb
      (footprint "GenericConn_01x02"
        (property "Reference" "J1")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    pcb = parse_kicad_pcb(src)
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (components
            (comp (ref "J1")
              (value "Power")
              (footprint "GenericConn_01x02")
              (property (name "Manufacturer") (value "TE"))
              (property (name "Manufacturer_Part_Number") (value "640456-2"))))
          (nets (net (code "1") (name "VCC") (node (ref "J1") (pin "1")))))
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    assert connectors[0].manufacturer is None
    assert connectors[0].mpn is None
    apply_netlist(connectors, netlist)
    assert connectors[0].manufacturer == "TE"
    assert connectors[0].mpn == "640456-2"


def test_apply_netlist_does_not_overwrite_existing_props() -> None:
    # PCB property already set — netlist props don't clobber.
    src = """
    (kicad_pcb
      (footprint "GenericConn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer" "Wago")
        (property "Manufacturer_Part_Number" "236-402")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    pcb = parse_kicad_pcb(src)
    netlist = parse_kicad_netlist(
        """
        (export (version "E")
          (components
            (comp (ref "J1")
              (property (name "Manufacturer") (value "TE"))
              (property (name "MPN") (value "640456-2"))))
          (nets (net (code "1") (name "VCC") (node (ref "J1") (pin "1")))))
        """
    )
    connectors = extract_connectors_from_pcb(pcb)
    apply_netlist(connectors, netlist)
    # PCB-set values stayed put.
    assert connectors[0].manufacturer == "Wago"
    assert connectors[0].mpn == "236-402"


# ---------------------------------------------------------------------------
# Property key normalization — case + space + underscore variants
# ---------------------------------------------------------------------------


def test_extract_property_key_lowercase() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "manufacturer" "Hirose")
        (property "mpn" "DF13-2P")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.manufacturer == "Hirose"
    assert conn.mpn == "DF13-2P"


def test_extract_property_key_with_spaces() -> None:
    # KiCad's UI lets users name custom fields with spaces.
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer Part Number" "B2B-XH-A(LF)(SN)")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.mpn == "B2B-XH-A(LF)(SN)"


def test_extract_property_key_with_hyphens() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer-Part-Number" "640456-2")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.mpn == "640456-2"


def test_extract_property_key_mixed_case_synonyms() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "MFG" "Molex")
        (property "Mfr_PN" "53261-1290")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.manufacturer == "Molex"
    assert conn.mpn == "53261-1290"


def test_extract_empty_property_value_skipped() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer" "")
        (property "Mfr" "Wago")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    # Empty Manufacturer is skipped; falls back to next synonym (Mfr).
    assert conn.manufacturer == "Wago"


def test_extract_manufacturer_name_field() -> None:
    # Real-world example from a Molex symbol: MANUFACTURER_NAME +
    # MANUFACTURER_PART_NUMBER (both uppercase, underscore-separated).
    src = """
    (kicad_pcb
      (footprint "Molex_Micro-Fit_43045-0413"
        (property "Reference" "J1")
        (property "MANUFACTURER_NAME" "Molex")
        (property "MANUFACTURER_PART_NUMBER" "0430450413")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5))
      )
    )
    """
    conn = extract_connectors_from_pcb(parse_kicad_pcb(src))[0]
    assert conn.manufacturer == "Molex"
    assert conn.mpn == "0430450413"


# ---------------------------------------------------------------------------
# Fuzzy property classifier
# ---------------------------------------------------------------------------


def test_classify_property_key_manufacturer() -> None:
    from splice_kicad_plugin.detect.connectors import _classify_property_key

    assert _classify_property_key("Manufacturer") == "manufacturer"
    assert _classify_property_key("MANUFACTURER_NAME") == "manufacturer"
    assert _classify_property_key("Mfr") == "manufacturer"
    assert _classify_property_key("Mfg") == "manufacturer"
    assert _classify_property_key("Vendor") == "manufacturer"
    assert _classify_property_key("OEM_Manufacturer") == "manufacturer"
    assert _classify_property_key("ComponentVendor") == "manufacturer"


def test_classify_property_key_mpn() -> None:
    from splice_kicad_plugin.detect.connectors import _classify_property_key

    assert _classify_property_key("MPN") == "mpn"
    assert _classify_property_key("Manufacturer_Part_Number") == "mpn"
    assert _classify_property_key("MfrPartNumber") == "mpn"
    assert _classify_property_key("Mfr_PN") == "mpn"
    # Composite "part number" in any form classifies as MPN even with a
    # manufacturer-like prefix.
    assert _classify_property_key("Mouser_Part_Number") == "mpn"
    assert _classify_property_key("OEMPartNum") == "mpn"
    assert _classify_property_key("part number") == "mpn"


def test_classify_property_key_neither() -> None:
    from splice_kicad_plugin.detect.connectors import _classify_property_key

    assert _classify_property_key("Reference") is None
    assert _classify_property_key("Datasheet") is None
    assert _classify_property_key("Description") is None
    assert _classify_property_key("Footprint") is None
    assert _classify_property_key("") is None
    assert _classify_property_key("Voltage") is None


def test_fuzzy_extract_picks_up_arbitrary_field_names() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "OEM_Manufacturer" "Hirose")
        (property "Distributor_Part_Number" "DF13-2P")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(
        parse_kicad_pcb(src), fuzzy_property_matching=True
    )[0]
    assert conn.manufacturer == "Hirose"
    assert conn.mpn == "DF13-2P"


def test_strict_mode_misses_unusual_field_names() -> None:
    # Same input, fuzzy=False — these aren't in the strict synonym list,
    # so neither should match.
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "OEM_Manufacturer" "Hirose")
        (property "Distributor_Part_Number" "DF13-2P")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(
        parse_kicad_pcb(src), fuzzy_property_matching=False
    )[0]
    # Neither key matches the strict synonym list.
    assert conn.manufacturer is None
    assert conn.mpn is None


def test_fuzzy_mpn_wins_over_manufacturer_for_part_number_keys() -> None:
    # 'Manufacturer_Part_Number' contains 'manufacturer' but the fuzzy
    # classifier treats it as MPN, not as a manufacturer field.
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "Manufacturer_Part_Number" "DF13-2P")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conn = extract_connectors_from_pcb(
        parse_kicad_pcb(src), fuzzy_property_matching=True
    )[0]
    assert conn.mpn == "DF13-2P"
    assert conn.manufacturer is None  # only one field, classified as MPN


def test_extract_mfr_name_and_mfg_name_variants() -> None:
    src = """
    (kicad_pcb
      (footprint "Conn_01x02"
        (property "Reference" "J1")
        (property "MFR_NAME" "TE Connectivity")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
      (footprint "Conn_01x02"
        (property "Reference" "J2")
        (property "Mfg_Name" "Phoenix Contact")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
      (footprint "Conn_01x02"
        (property "Reference" "J3")
        (property "Vendor_Name" "Wago")
        (pad "1" thru_hole circle (at 0 0) (size 1.5 1.5)))
    )
    """
    conns = extract_connectors_from_pcb(parse_kicad_pcb(src))
    by_ref = {c.reference: c for c in conns}
    assert by_ref["J1"].manufacturer == "TE Connectivity"
    assert by_ref["J2"].manufacturer == "Phoenix Contact"
    assert by_ref["J3"].manufacturer == "Wago"
