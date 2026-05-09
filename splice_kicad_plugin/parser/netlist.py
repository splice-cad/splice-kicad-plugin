"""KiCad netlist (``.net``) parser — s-expression form.

Direct port of ``kicadParser.ts:293-397``. The netlist is the canonical post-
elaboration view of the schematic: hierarchical sheets are flattened, buses
are expanded, multi-unit symbols are merged, and every net node carries
``(ref, pin, pinfunction, pintype)``. This is what the conductor-chaining
algorithm consumes to wire connectors together (RFC-003b §4).

The kicadxml form (``kicad-cli sch export netlist --format kicadxml``) is a
separate follow-up — that one uses XML rather than s-expressions.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

from dataclasses import dataclass, field
from typing import Mapping

from ..errors import NetlistFormatError
from .sexpr import (
    SExpr,
    find_all_children,
    find_child,
    get_string,
    is_list,
    parse_sexpr,
)


@dataclass(frozen=True)
class KicadNetlistNode:
    """One pin in a net — a ``(node (ref "J1") (pin "3") …)`` form."""

    ref: str
    pin: str
    pin_function: str | None = None  # KiCad <pinfunction>
    pin_type: str | None = None  # KiCad <pintype>


@dataclass(frozen=True)
class KicadNet:
    """A named net, e.g. ``GND``, ``CAN_H``, ``Net-(J1-Pad3)``."""

    code: str
    name: str
    nodes: tuple[KicadNetlistNode, ...]


@dataclass(frozen=True)
class KicadNetlistComponent:
    """A component as it appears in the netlist's ``(components …)`` block."""

    ref: str
    value: str
    footprint: str
    properties: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KicadNetlist:
    """The full parsed netlist.

    ``nets_by_ref`` is a convenience lookup: ``nets_by_ref["J1"]["3"]`` returns
    the net name connected to pin 3 of J1, or raises KeyError if unconnected.
    """

    version: str
    components: tuple[KicadNetlistComponent, ...]
    nets: tuple[KicadNet, ...]
    nets_by_ref: Mapping[str, Mapping[str, str]]


def parse_kicad_netlist(content: str) -> KicadNetlist:
    """Parse a ``.net`` (s-expression) file into a :class:`KicadNetlist`.

    Raises :class:`NetlistFormatError` if the root form isn't ``(export …)``.
    """
    expr = parse_sexpr(content)
    if not is_list(expr, "export"):
        raise NetlistFormatError(
            "Invalid KiCad netlist file - expected (export ...) at top level"
        )
    assert isinstance(expr, list)  # narrowed

    version = ""
    version_node = find_child(expr, "version")
    if version_node is not None and len(version_node) >= 2:
        version = get_string(version_node[1])

    components = _parse_components(expr)
    nets, nets_by_ref = _parse_nets(expr)

    return KicadNetlist(
        version=version,
        components=tuple(components),
        nets=tuple(nets),
        nets_by_ref=nets_by_ref,
    )


def _parse_components(expr: list[SExpr]) -> list[KicadNetlistComponent]:
    out: list[KicadNetlistComponent] = []
    components_node = find_child(expr, "components")
    if components_node is None:
        return out

    for comp in find_all_children(components_node, "comp"):
        ref_node = find_child(comp, "ref")
        if ref_node is None or len(ref_node) < 2:
            continue
        ref = get_string(ref_node[1])
        if not ref:
            continue

        value = ""
        value_node = find_child(comp, "value")
        if value_node is not None and len(value_node) >= 2:
            value = get_string(value_node[1])

        footprint = ""
        fp_node = find_child(comp, "footprint")
        if fp_node is not None and len(fp_node) >= 2:
            footprint = get_string(fp_node[1])

        # (property (name "X") (value "Y"))
        properties: dict[str, str] = {}
        for prop in find_all_children(comp, "property"):
            name_node = find_child(prop, "name")
            val_node = find_child(prop, "value")
            if (
                name_node is not None
                and val_node is not None
                and len(name_node) >= 2
                and len(val_node) >= 2
            ):
                properties[get_string(name_node[1])] = get_string(val_node[1])

        out.append(
            KicadNetlistComponent(
                ref=ref, value=value, footprint=footprint, properties=properties
            )
        )

    return out


def _parse_nets(
    expr: list[SExpr],
) -> tuple[list[KicadNet], dict[str, dict[str, str]]]:
    nets: list[KicadNet] = []
    nets_by_ref: dict[str, dict[str, str]] = {}

    nets_node = find_child(expr, "nets")
    if nets_node is None:
        return nets, nets_by_ref

    for net_expr in find_all_children(nets_node, "net"):
        code = ""
        code_node = find_child(net_expr, "code")
        if code_node is not None and len(code_node) >= 2:
            code = get_string(code_node[1])

        name = ""
        name_node = find_child(net_expr, "name")
        if name_node is not None and len(name_node) >= 2:
            name = get_string(name_node[1])

        nodes: list[KicadNetlistNode] = []
        for node_expr in find_all_children(net_expr, "node"):
            ref_node = find_child(node_expr, "ref")
            pin_node = find_child(node_expr, "pin")
            if (
                ref_node is None
                or pin_node is None
                or len(ref_node) < 2
                or len(pin_node) < 2
            ):
                continue
            ref = get_string(ref_node[1])
            pin = get_string(pin_node[1])
            if not ref or not pin:
                continue

            pin_function: str | None = None
            pin_type: str | None = None
            pf_node = find_child(node_expr, "pinfunction")
            if pf_node is not None and len(pf_node) >= 2:
                pin_function = get_string(pf_node[1])
            pt_node = find_child(node_expr, "pintype")
            if pt_node is not None and len(pt_node) >= 2:
                pin_type = get_string(pt_node[1])

            nodes.append(
                KicadNetlistNode(
                    ref=ref,
                    pin=pin,
                    pin_function=pin_function,
                    pin_type=pin_type,
                )
            )
            nets_by_ref.setdefault(ref, {})[pin] = name

        nets.append(KicadNet(code=code, name=name, nodes=tuple(nodes)))

    return nets, nets_by_ref
