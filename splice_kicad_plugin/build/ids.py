"""Stable, deterministic ID generation for PlanData entities.

IDs are UUID5-derived from the connector's schematic reference, so re-exporting
the same KiCad project produces identical node / pin / BOM IDs. The Splice
editor can then recognize a re-import as an update of the same shape rather
than a pile of duplicates.

The namespace UUID is **load-bearing**: change it and every ID changes, which
breaks round-trips. It is pinned by ``tests/test_ids.py``.

Node and pin IDs use distinct namespacing strings (``"node:…"`` vs ``"pin:…"``)
so the same reference can't collide across entity kinds. Shapes mirror the
``generate*Id`` helpers in ``frontend/src/interfaces/planInterfaces.ts``.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

from uuid import UUID, uuid5

# Pinned project namespace — DO NOT CHANGE (see tests/test_ids.py).
PROJECT_NAMESPACE = UUID("8c2e6e4a-9e2b-4d8a-8c0a-1a2b3c4d5e6f")

# Number of hex chars from the UUID5 digest used as the ID body.
_HEX_LEN = 20


def _body(namespaced: str) -> str:
    """Deterministic lowercase hex body for a namespaced key."""
    return uuid5(PROJECT_NAMESPACE, namespaced).hex[:_HEX_LEN]


def stable_node_id(reference: str) -> str:
    """Stable ``comp_…`` PlanNode ID for a connector reference."""
    return "comp_" + _body(f"node:{reference}")


def stable_pin_id(reference: str, pin_number: str) -> str:
    """Stable ``pin_…`` ComponentPin ID for a (reference, pad number) pair."""
    return "pin_" + _body(f"pin:{reference}:{pin_number}")


def stable_bom_entry_id(reference: str) -> str:
    """Stable ``bom_…`` BomEntry ID for a connector reference."""
    return "bom_" + _body(f"bom:{reference}")
