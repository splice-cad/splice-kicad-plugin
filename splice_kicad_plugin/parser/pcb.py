"""KiCad ``.kicad_pcb`` parser.

Direct port of ``kicadParser.ts:472-610`` from the splice frontend. Extracts
footprints + pads + properties from a parsed S-expression tree. Supports both
KiCad 5 (``fp_text reference``) and KiCad 6+ (``property "Reference"``) forms.

Out of scope (intentionally): copper, vias, zones, layers, board outline. Those
are part of the PCB layout and don't matter for harness extraction.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

from collections.abc import Mapping
from dataclasses import dataclass

from ..errors import InvalidKicadFileError
from .sexpr import (
    SExpr,
    find_all_children,
    find_child,
    get_string,
    is_list,
    parse_sexpr,
)


@dataclass(frozen=True)
class KicadPad:
    number: str
    type: str  # "thru_hole" | "smd" | "np_thru_hole" | "connect"
    shape: str  # "rect" | "circle" | "oval" | "roundrect" | "custom"
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class KicadFootprint:
    reference: str  # "J1", "J2", etc.
    footprint: str  # full library:name path or bare name
    value: str  # component value (often MPN)
    x: float
    y: float
    rotation: float
    pads: tuple[KicadPad, ...]
    properties: Mapping[str, str]


@dataclass(frozen=True)
class KicadPcbData:
    version: str
    generator: str
    footprints: tuple[KicadFootprint, ...]


def parse_kicad_pcb(content: str) -> KicadPcbData:
    """Parse a ``.kicad_pcb`` file's text content into a :class:`KicadPcbData`.

    Raises :class:`InvalidKicadFileError` if the root form isn't ``(kicad_pcb …)``.
    """
    expr = parse_sexpr(content)
    if not is_list(expr, "kicad_pcb"):
        raise InvalidKicadFileError(
            "Invalid KiCad PCB file - expected (kicad_pcb ...) at top level"
        )
    assert isinstance(expr, list)  # narrowed by is_list

    version = ""
    version_node = find_child(expr, "version")
    if version_node is not None and len(version_node) >= 2:
        version = get_string(version_node[1])

    generator = ""
    generator_node = find_child(expr, "generator")
    if generator_node is not None and len(generator_node) >= 2:
        generator = get_string(generator_node[1])

    footprints: list[KicadFootprint] = []
    for fp_expr in find_all_children(expr, "footprint"):
        fp = _parse_footprint(fp_expr)
        if fp is not None:
            footprints.append(fp)

    return KicadPcbData(
        version=version,
        generator=generator,
        footprints=tuple(footprints),
    )


def _safe_float(s: str) -> float:
    """``parseFloat(str) || 0`` parity — non-numeric input becomes 0.0."""
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _parse_footprint(expr: list[SExpr]) -> KicadFootprint | None:
    if len(expr) < 2:
        return None

    footprint_name = get_string(expr[1])

    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    at_expr = find_child(expr, "at")
    if at_expr is not None and len(at_expr) >= 3:
        x = _safe_float(get_string(at_expr[1]))
        y = _safe_float(get_string(at_expr[2]))
        if len(at_expr) >= 4:
            rotation = _safe_float(get_string(at_expr[3]))

    # KiCad 6+: (property "Reference" "J1" ...)
    reference = ""
    value = ""
    props: dict[str, str] = {}
    for prop in find_all_children(expr, "property"):
        if len(prop) >= 3:
            name = get_string(prop[1])
            val = get_string(prop[2])
            props[name] = val
            if name == "Reference":
                reference = val
            elif name == "Value":
                value = val

    # KiCad 5 fallback: (fp_text reference "J1" ...) / (fp_text value "..." ...)
    if not reference:
        for fp_text in find_all_children(expr, "fp_text"):
            if len(fp_text) >= 3:
                text_type = get_string(fp_text[1])
                text_value = get_string(fp_text[2])
                if text_type == "reference":
                    reference = text_value
                elif text_type == "value":
                    value = text_value

    pads: list[KicadPad] = []
    for pad_expr in find_all_children(expr, "pad"):
        pad = _parse_pad(pad_expr)
        if pad is not None:
            pads.append(pad)

    return KicadFootprint(
        reference=reference,
        footprint=footprint_name,
        value=value,
        x=x,
        y=y,
        rotation=rotation,
        pads=tuple(pads),
        properties=props,
    )


def _parse_pad(expr: list[SExpr]) -> KicadPad | None:
    if len(expr) < 4:
        return None

    number = get_string(expr[1])
    pad_type = get_string(expr[2])
    shape = get_string(expr[3])

    x: float = 0.0
    y: float = 0.0
    at_expr = find_child(expr, "at")
    if at_expr is not None and len(at_expr) >= 3:
        x = _safe_float(get_string(at_expr[1]))
        y = _safe_float(get_string(at_expr[2]))

    width: float = 0.0
    height: float = 0.0
    size_expr = find_child(expr, "size")
    if size_expr is not None and len(size_expr) >= 3:
        width = _safe_float(get_string(size_expr[1]))
        height = _safe_float(get_string(size_expr[2]))

    return KicadPad(
        number=number,
        type=pad_type,
        shape=shape,
        x=x,
        y=y,
        width=width,
        height=height,
    )
