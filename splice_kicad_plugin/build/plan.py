"""PlanData assembly — converts ExtractedConnectors into a Splice PlanData JSON.

Per RFC-003b §3 (the parts that still apply for the no-conductors v1):

- Each ``ExtractedConnector`` becomes one ``PlanNode`` of type ``component``.
- Each ``ExtractedPin`` becomes one ``ComponentPin`` with a stable ID.
- ``pin.label`` = pin number; ``pin.function`` = net name (from the netlist,
  if applied).
- No conductors, links, nets, wire groups, or cables in the output — those
  are user-authored after import.

Position is auto-gridded so the imported plan lands on a usable layout.
Splice's in-app Auto-arrange (ELK) can re-flow as needed.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

from typing import Sequence

from ..detect.connectors import ExtractedConnector, ExtractedPin
from ..version import SCHEMA_VERSION, __version__
from .ids import stable_bom_entry_id, stable_node_id, stable_pin_id

# Auto-grid layout for connector PlanNodes. Per RFC-003b §3.
_COL_W = 240
_ROW_H = 180
_COLS = 6


def _auto_grid_position(index: int) -> dict:
    return {"x": (index % _COLS) * _COL_W, "y": (index // _COLS) * _ROW_H}


def _build_pin(splice_ref: str, pin: ExtractedPin) -> dict:
    """Construct a ComponentPin entry."""
    out: dict = {
        "id": stable_pin_id(splice_ref, pin.number),
        "label": pin.number,
    }
    if pin.function is not None:
        out["function"] = pin.function
    return out


def _build_connector_meta(conn: ExtractedConnector) -> dict:
    """Pack KiCad metadata into a ``meta`` block on the PlanNode.

    The frontend's ``PlanNode`` type doesn't define ``meta`` today (RFC-003b §3
    flags this); we still emit the field so the data is available once a
    small frontend addition is made. JSON consumers should ignore unknown
    keys until then.
    """
    meta: dict = {"kicad.splice_ref": conn.reference}
    if conn.footprint:
        meta["kicad.footprint"] = conn.footprint
    if conn.value:
        meta["kicad.value"] = conn.value
    if conn.manufacturer is not None:
        meta["kicad.manufacturer"] = conn.manufacturer
    if conn.series is not None:
        meta["kicad.series"] = conn.series
    if conn.mpn is not None:
        meta["kicad.mpn"] = conn.mpn
    if conn.pitch_mm is not None:
        meta["kicad.pitch_mm"] = conn.pitch_mm
    if conn.rows is not None:
        meta["kicad.rows"] = conn.rows
    if conn.mounting_style is not None:
        meta["kicad.mounting_style"] = conn.mounting_style
    if conn.source_sheet is not None:
        meta["kicad.source_sheet"] = conn.source_sheet
    return meta


def _build_node(
    index: int,
    conn: ExtractedConnector,
    *,
    bom_entry_id: str | None = None,
) -> dict:
    """Construct one ``PlanNode`` of type ``component``.

    ``bom_entry_id`` (when supplied) links the node to its BOM entry so the
    Splice frontend can render manufacturer / MPN next to the connector.
    """
    splice_ref = conn.reference  # Splice_Ref override is a future schematic-parser job
    node: dict = {
        "id": stable_node_id(splice_ref),
        "type": "component",
        "label": conn.reference,
        "shape": "rectangular",
        "position": _auto_grid_position(index),
        "pins": [_build_pin(splice_ref, p) for p in conn.pins],
        "meta": _build_connector_meta(conn),
    }
    if conn.value:
        node["name"] = conn.value
    if bom_entry_id is not None:
        node["bomEntryId"] = bom_entry_id
    return node


def _build_bom_entry(conn: ExtractedConnector) -> dict:
    """Build a ``BomEntry`` for the connector.

    Always created, even when manufacturer / MPN are unset — gives the user
    a placeholder slot in the BOM to fill in later. Stable IDs derived from
    the connector's reference (or future ``Splice_Ref``).

    Frontend type: see ``BomEntry`` in
    ``frontend/src/interfaces/planInterfaces.ts``. Required fields are
    ``id`` / ``mpn`` / ``manufacturer`` / ``type``; ``spec`` carries
    type-specific data (positions, series, pin labels & functions).
    """
    splice_ref = conn.reference
    entry: dict = {
        "id": stable_bom_entry_id(splice_ref),
        "mpn": conn.mpn or "",
        "manufacturer": conn.manufacturer or "",
        "type": "connector",
    }
    if conn.value:
        entry["description"] = conn.value

    spec: dict = {}
    if conn.pin_count:
        spec["positions"] = conn.pin_count
    if conn.series:
        spec["series"] = conn.series
    if conn.pins:
        spec["pin_labels"] = [p.number for p in conn.pins]
        functions = [p.function for p in conn.pins]
        if any(functions):
            # Per BomEntrySpec, missing entries are typed as undefined; we use
            # None on the Python side, which serializes to JSON null.
            spec["pin_functions"] = functions
    if spec:
        entry["spec"] = spec
    return entry


def build_plan_data(
    connectors: Sequence[ExtractedConnector],
    *,
    project_name: str | None = None,
) -> dict:
    """Assemble the PlanData JSON document for the working-plan endpoint.

    Each connector becomes one ``PlanNode`` of type ``component`` plus one
    ``BomEntry`` in ``PlanData.bom``. The node's ``bomEntryId`` references
    its BOM entry so the Splice frontend can render manufacturer / MPN
    next to the component.
    """
    nodes: dict = {}
    bom: list[dict] = []
    for i, conn in enumerate(connectors):
        bom_entry = _build_bom_entry(conn)
        bom.append(bom_entry)
        node = _build_node(i, conn, bom_entry_id=bom_entry["id"])
        nodes[node["id"]] = node

    plan: dict = {
        "schemaVersion": SCHEMA_VERSION,
        "nodes": nodes,
        "links": {},
        "nets": {},
        "conductors": {},
        "conductorSplices": {},
        "wireGroups": {},
        "cables": {},
        "signals": {},
        "mates": [],
        "deviceGroups": [],
        "bom": bom,
        "source": {
            "tool": "kicad-plugin",
            "version": __version__,
            "protocol": "splice-kicad-plugin/1",
        },
    }
    if project_name:
        plan["source"]["project"] = project_name
    return plan
