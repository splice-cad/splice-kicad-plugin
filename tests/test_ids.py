"""Tests for ``splice_kicad_plugin.build.ids``.

The v1 export only emits PlanNodes (with pin functions from netlist nets); no
conductors / links / wire groups. So only the two stable-ID generators
(node, pin) are exercised here.
"""

import re

from splice_kicad_plugin.build.ids import (
    PROJECT_NAMESPACE,
    stable_node_id,
    stable_pin_id,
)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_stable_node_id_is_deterministic() -> None:
    assert stable_node_id("J1") == stable_node_id("J1")


def test_stable_node_id_distinguishes_inputs() -> None:
    assert stable_node_id("J1") != stable_node_id("J2")


def test_stable_pin_id_is_deterministic() -> None:
    assert stable_pin_id("J1", "3") == stable_pin_id("J1", "3")


def test_stable_pin_id_distinguishes_ref_and_pin() -> None:
    a = stable_pin_id("J1", "3")
    b = stable_pin_id("J2", "3")
    c = stable_pin_id("J1", "4")
    assert a != b
    assert a != c
    assert b != c


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


_HEX20 = re.compile(r"^[a-f0-9]{20}$")


def test_stable_node_id_format() -> None:
    nid = stable_node_id("J1")
    assert nid.startswith("comp_")
    assert _HEX20.match(nid[len("comp_"):])


def test_stable_pin_id_format() -> None:
    pid = stable_pin_id("J1", "1")
    assert pid.startswith("pin_")
    assert _HEX20.match(pid[len("pin_"):])


def test_node_and_pin_namespacing_dont_collide() -> None:
    # Same input string would collide if node+pin shared a namespace prefix.
    # We use different namespacing strings ("node:..." vs "pin:..."), so they
    # produce different hex bodies.
    assert (
        stable_node_id("J1")[len("comp_"):]
        != stable_pin_id("J1", "1")[len("pin_"):]
    )


# ---------------------------------------------------------------------------
# Lock-down test: the namespace UUID is load-bearing
# ---------------------------------------------------------------------------


def test_namespace_uuid_is_pinned() -> None:
    # If anyone changes this, every stable ID changes, breaking round-trips.
    assert str(PROJECT_NAMESPACE) == "8c2e6e4a-9e2b-4d8a-8c0a-1a2b3c4d5e6f"
