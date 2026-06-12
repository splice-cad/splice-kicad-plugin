"""Tests for ``splice_kicad_plugin.build.plan``."""

import json

from splice_kicad_plugin.build.ids import (
    stable_bom_entry_id,
    stable_node_id,
    stable_pin_id,
)
from splice_kicad_plugin.build.plan import build_plan_data
from splice_kicad_plugin.detect.connectors import ExtractedConnector, ExtractedPin
from splice_kicad_plugin.version import SCHEMA_VERSION, __version__


def _conn(
    ref: str,
    *,
    pins: list[tuple[str, str | None]] = (),
    footprint: str = "Connector_Generic:Conn_01x02",
    value: str = "",
    manufacturer: str | None = None,
    mpn: str | None = None,
    pitch_mm: float | None = None,
) -> ExtractedConnector:
    return ExtractedConnector(
        reference=ref,
        footprint=footprint,
        value=value,
        pins=[ExtractedPin(number=num, function=fn) for num, fn in pins],
        x=0.0,
        y=0.0,
        manufacturer=manufacturer,
        mpn=mpn,
        pitch_mm=pitch_mm,
    )


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


def test_top_level_keys_present() -> None:
    plan = build_plan_data([])
    expected = {
        "schemaVersion",
        "nodes",
        "links",
        "nets",
        "conductors",
        "conductorSplices",
        "wireGroups",
        "cables",
        "signals",
        "mates",
        "deviceGroups",
        "bom",
        "source",
    }
    assert set(plan.keys()) == expected


def test_schema_version_pinned() -> None:
    plan = build_plan_data([])
    assert plan["schemaVersion"] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 2


def test_empty_connectors_yields_empty_nodes() -> None:
    plan = build_plan_data([])
    assert plan["nodes"] == {}
    # Other collections default to empty dicts/lists.
    assert plan["links"] == {}
    assert plan["nets"] == {}
    assert plan["conductors"] == {}


def test_source_metadata() -> None:
    plan = build_plan_data([])
    assert plan["source"]["tool"] == "kicad-plugin"
    assert plan["source"]["version"] == __version__
    assert plan["source"]["protocol"] == "splice-kicad-plugin/1"
    # No project unless explicitly named.
    assert "project" not in plan["source"]


def test_source_includes_project_when_named() -> None:
    plan = build_plan_data([], project_name="my-harness")
    assert plan["source"]["project"] == "my-harness"


# ---------------------------------------------------------------------------
# Node construction
# ---------------------------------------------------------------------------


def test_one_connector_one_node() -> None:
    conn = _conn("J1", pins=[("1", "+5V"), ("2", "GND")])
    plan = build_plan_data([conn])
    assert len(plan["nodes"]) == 1
    node_id = stable_node_id("J1")
    node = plan["nodes"][node_id]
    assert node["id"] == node_id
    assert node["type"] == "component"
    assert node["label"] == "J1"
    assert node["shape"] == "rectangular"


def test_node_keys_and_node_ids_match() -> None:
    plan = build_plan_data([_conn("J1"), _conn("J2"), _conn("J3")])
    for node_id, node in plan["nodes"].items():
        assert node_id == node["id"]


def test_node_value_field_populates_name() -> None:
    conn = _conn("J1", value="Power Input")
    plan = build_plan_data([conn])
    node = plan["nodes"][stable_node_id("J1")]
    assert node["name"] == "Power Input"


def test_node_omits_name_when_value_empty() -> None:
    conn = _conn("J1", value="")
    plan = build_plan_data([conn])
    node = plan["nodes"][stable_node_id("J1")]
    assert "name" not in node


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------


def test_pin_label_is_pin_number() -> None:
    conn = _conn("J1", pins=[("1", "+5V"), ("2", "GND"), ("A1", "TX")])
    plan = build_plan_data([conn])
    pins = plan["nodes"][stable_node_id("J1")]["pins"]
    assert [p["label"] for p in pins] == ["1", "2", "A1"]


def test_pin_function_set_from_netlist() -> None:
    conn = _conn("J1", pins=[("1", "+5V"), ("2", "GND")])
    plan = build_plan_data([conn])
    pins = plan["nodes"][stable_node_id("J1")]["pins"]
    assert pins[0]["function"] == "+5V"
    assert pins[1]["function"] == "GND"


def test_pin_function_omitted_when_none() -> None:
    conn = _conn("J1", pins=[("1", None), ("2", None)])
    plan = build_plan_data([conn])
    pins = plan["nodes"][stable_node_id("J1")]["pins"]
    for p in pins:
        assert "function" not in p


def test_pin_id_is_stable() -> None:
    conn = _conn("J1", pins=[("1", "VCC")])
    plan = build_plan_data([conn])
    pin = plan["nodes"][stable_node_id("J1")]["pins"][0]
    assert pin["id"] == stable_pin_id("J1", "1")


# ---------------------------------------------------------------------------
# Position auto-grid
# ---------------------------------------------------------------------------


def test_first_seven_connectors_grid() -> None:
    plan = build_plan_data([_conn(f"J{i}") for i in range(1, 8)])
    # 6 columns of 240 px each, 180 px row height.
    expected = [
        (0, 0),
        (240, 0),
        (480, 0),
        (720, 0),
        (960, 0),
        (1200, 0),
        (0, 180),
    ]
    # Iterate in insertion order — Python 3.7+ dicts preserve it.
    actual = [(n["position"]["x"], n["position"]["y"]) for n in plan["nodes"].values()]
    assert actual == expected


# ---------------------------------------------------------------------------
# Meta block
# ---------------------------------------------------------------------------


def test_meta_block_carries_kicad_fields() -> None:
    conn = _conn(
        "J1",
        pins=[("1", "VCC")],
        footprint="Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm",
        value="Power",
        manufacturer="JST",
        mpn="S2B-PH-K-S",
        pitch_mm=2.0,
    )
    plan = build_plan_data([conn])
    meta = plan["nodes"][stable_node_id("J1")]["meta"]
    assert meta["kicad.splice_ref"] == "J1"
    assert meta["kicad.footprint"] == "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm"
    assert meta["kicad.value"] == "Power"
    assert meta["kicad.manufacturer"] == "JST"
    assert meta["kicad.mpn"] == "S2B-PH-K-S"
    assert meta["kicad.pitch_mm"] == 2.0


def test_meta_block_omits_unset_fields() -> None:
    conn = _conn("J1", pins=[("1", None)], footprint="x", value="")
    meta = build_plan_data([conn])["nodes"][stable_node_id("J1")]["meta"]
    # Only fields that have values appear; the rest are absent.
    assert "kicad.manufacturer" not in meta
    assert "kicad.mpn" not in meta
    assert "kicad.pitch_mm" not in meta
    assert "kicad.value" not in meta


# ---------------------------------------------------------------------------
# Determinism + serializability
# ---------------------------------------------------------------------------


def test_two_runs_produce_identical_node_and_pin_ids() -> None:
    conn = _conn("J1", pins=[("1", "VCC"), ("2", "GND")])
    a = build_plan_data([conn])
    b = build_plan_data([conn])
    assert set(a["nodes"]) == set(b["nodes"])
    pins_a = a["nodes"][stable_node_id("J1")]["pins"]
    pins_b = b["nodes"][stable_node_id("J1")]["pins"]
    assert [p["id"] for p in pins_a] == [p["id"] for p in pins_b]


# ---------------------------------------------------------------------------
# BOM entries
# ---------------------------------------------------------------------------


def test_bom_entry_per_connector() -> None:
    plan = build_plan_data([_conn("J1"), _conn("J2"), _conn("J3")])
    assert len(plan["bom"]) == 3
    ids = {e["id"] for e in plan["bom"]}
    assert ids == {stable_bom_entry_id(r) for r in ("J1", "J2", "J3")}


def test_bom_entry_carries_mpn_and_manufacturer() -> None:
    conn = _conn(
        "J1",
        manufacturer="Molex",
        mpn="0430450413",
        pins=[("1", "+5V"), ("2", "GND"), ("3", "CAN_H"), ("4", "CAN_L")],
    )
    plan = build_plan_data([conn])
    entry = plan["bom"][0]
    assert entry["manufacturer"] == "Molex"
    assert entry["mpn"] == "0430450413"
    assert entry["type"] == "connector"


def test_bom_entry_includes_positions_and_pin_labels() -> None:
    conn = _conn(
        "J1",
        manufacturer="JST",
        mpn="S2B-PH-K",
        pins=[("1", "+5V"), ("2", "GND")],
    )
    plan = build_plan_data([conn])
    entry = plan["bom"][0]
    assert entry["spec"]["positions"] == 2
    assert entry["spec"]["pin_labels"] == ["1", "2"]
    assert entry["spec"]["pin_functions"] == ["+5V", "GND"]


def test_bom_entry_omits_pin_functions_when_all_unset() -> None:
    conn = _conn("J1", pins=[("1", None), ("2", None)])
    plan = build_plan_data([conn])
    entry = plan["bom"][0]
    # pin_labels still emitted; pin_functions skipped when nothing's populated.
    assert entry["spec"]["pin_labels"] == ["1", "2"]
    assert "pin_functions" not in entry["spec"]


def test_bom_entry_empty_metadata_still_creates_placeholder() -> None:
    # No mfr / mpn / value — entry still created so the user can fill it
    # in inside the Splice editor.
    conn = _conn("J1", pins=[("1", None)])
    plan = build_plan_data([conn])
    entry = plan["bom"][0]
    assert entry["manufacturer"] == ""
    assert entry["mpn"] == ""
    assert entry["type"] == "connector"


def test_bom_entry_description_from_value() -> None:
    conn = _conn("J1", value="Power Input", pins=[("1", None)])
    plan = build_plan_data([conn])
    assert plan["bom"][0]["description"] == "Power Input"


def test_node_bom_entry_id_references_bom_entry() -> None:
    plan = build_plan_data([_conn("J1", manufacturer="JST", mpn="S2B-PH-K")])
    node = next(iter(plan["nodes"].values()))
    bom_entry = plan["bom"][0]
    assert node["bomEntryId"] == bom_entry["id"]


def test_bom_entries_stable_across_runs() -> None:
    conn = _conn("J1", manufacturer="Molex", mpn="0430450413", pins=[("1", "+5V"), ("2", "GND")])
    a = build_plan_data([conn])
    b = build_plan_data([conn])
    assert [e["id"] for e in a["bom"]] == [e["id"] for e in b["bom"]]


def test_plan_is_json_serializable() -> None:
    conn = _conn(
        "J1",
        pins=[("1", "+5V"), ("2", "GND")],
        manufacturer="JST",
        pitch_mm=2.0,
    )
    plan = build_plan_data([conn], project_name="demo")
    s = json.dumps(plan, indent=2, sort_keys=True)
    parsed = json.loads(s)
    assert parsed == plan
