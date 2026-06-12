"""Connector / jumper detection from parsed PCB data, with optional pin-function
enrichment from a netlist.

Direct port of ``kicadParser.ts:894-1087`` plus the ``applyNetlistToConnectors``
behavior (lines 403-463). Detects connectors by reference designator prefix
(``J|CN|CON|P|X``) plus footprint name regex (``connector_*``, ``jst_*``,
``molex_*``, ``header``, ``socket``, ``plug``, ``_conn$``, …). Jumpers aren't a
separate type — they're connectors that happen to be jumpered together by the
user.

Filters out mounting holes (``MP*``/``MH*``/``MTG*``), non-plated through-holes,
and unnumbered pads.

When a netlist is supplied, each pin's ``function`` is set to the net name it
participates in. That net-name-as-pin-function is the goal of v1: the import
produces components annotated with the signal each pin carries, without
synthesizing conductor records between them.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..parser.netlist import KicadNetlist
from ..parser.pcb import KicadFootprint, KicadPad, KicadPcbData
from .footprint_name import parse_footprint_name
from .patterns import (
    DEFAULT_CONNECTOR_PREFIXES,
    EXCLUDED_PAD_PREFIXES_RE,
    EXCLUDED_PAD_TYPES,
    FOOTPRINT_PATTERNS,
)

# Property keys to look at when pulling manufacturer/MPN out of a KiCad
# footprint or netlist component. Stored in normalized form (see
# ``_normalize_property_key``) so user variants like "Manufacturer Part Number"
# (with spaces) or "manufacturer_part_number" (lowercase) all match.
# Order matters — first hit wins.
_MFR_KEYS: tuple[str, ...] = (
    "manufacturer",
    "manufacturername",
    "mfr",
    "mfrname",
    "mfg",
    "mfgname",
    "make",
    "maker",
    "vendor",
    "vendorname",
)
_MPN_KEYS: tuple[str, ...] = (
    "manufacturerpartnumber",
    "mfrpartnumber",
    "mfgpartnumber",
    "mpn",
    "mfrpn",
    "mfgpn",
    "partnumber",
    "pn",
)


def _normalize_property_key(s: str) -> str:
    """Lower-case + drop spaces / underscores / hyphens.

    KiCad property keys are case-sensitive in storage but users freely mix
    'Manufacturer Part Number', 'Manufacturer_Part_Number', 'mpn', etc.
    Normalize so any of those map to the same lookup form.
    """
    return s.lower().replace("_", "").replace(" ", "").replace("-", "")


# ---------------------------------------------------------------------------
# Fuzzy / token-based property classifier
#
# For the strict path we use ``_normalize_property_key`` + a synonym list.
# That misses keys we haven't enumerated. The fuzzy path tokenizes the key
# into word components (camelCase / underscore / hyphen / space all count as
# boundaries) and asks: "do these tokens look like a manufacturer field, an
# MPN field, or neither?".
#
# Examples:
#   MANUFACTURER_NAME       → ["manufacturer", "name"] → manufacturer
#   Manufacturer_Part_Number → ["manufacturer", "part", "number"] → MPN
#   MfrPartNumber            → ["mfr", "part", "number"] → MPN
#   Mouser_Part_Number       → ["mouser", "part", "number"] → MPN
#   Datasheet                → ["datasheet"] → None
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALPHANUM_RE = re.compile(r"[^a-zA-Z0-9]+")

# Tokens that, when present in the key, classify it as that kind of field.
# Order: MPN check first — "manufacturer_part_number" must NOT be classified
# as a manufacturer field just because it contains "manufacturer".
_MPN_TOKEN_SET: frozenset[str] = frozenset({"mpn", "partnumber", "partnum", "pn"})
_MFR_TOKEN_SET: frozenset[str] = frozenset(
    {
        "manufacturer",
        "manuf",
        "mfr",
        "mfg",
        "vendor",
        "maker",
        "make",
        "supplier",
        "company",
        "brand",
    }
)


def _tokenize_property_key(s: str) -> list[str]:
    """Split a property key on camel-case + non-alphanumeric boundaries."""
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", s)
    spaced = _NON_ALPHANUM_RE.sub(" ", spaced).lower()
    return [t for t in spaced.split() if t]


def _classify_property_key(key: str) -> str | None:
    """Return ``'mpn'``, ``'manufacturer'``, or ``None`` for a property key."""
    tokens = _tokenize_property_key(key)
    if not tokens:
        return None
    # Composite "part number" beats single-token "part" — covers
    # Manufacturer_Part_Number, MfrPartNum, Mouser Part Number, etc.
    if "part" in tokens and ("number" in tokens or "num" in tokens):
        return "mpn"
    if any(t in _MPN_TOKEN_SET for t in tokens):
        return "mpn"
    if any(t in _MFR_TOKEN_SET for t in tokens):
        return "manufacturer"
    return None


@dataclass
class ExtractedPin:
    """One pin on an extracted connector.

    ``number`` is the KiCad pad/pin identifier (``"1"``, ``"A1"``, ``"GND"``).
    ``function`` is the signal carried by this pin — by default empty, set
    to the net name by :func:`apply_netlist`.
    """

    number: str
    function: str | None = None


@dataclass
class ExtractedConnector:
    """A connector or jumper extracted from a KiCad project.

    Pins start with just their ``number``; richer metadata (``function`` from
    the netlist) is filled in by later passes.
    """

    reference: str
    footprint: str
    value: str
    pins: list[ExtractedPin]
    x: float
    y: float
    manufacturer: str | None = None
    series: str | None = None
    mpn: str | None = None
    pitch_mm: float | None = None
    rows: int | None = None
    mounting_style: str | None = None
    source_sheet: str | None = None

    @property
    def pin_count(self) -> int:
        return len(self.pins)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _prefix_re(prefixes: Sequence[str]) -> re.Pattern:
    return re.compile(rf"^({'|'.join(re.escape(p) for p in prefixes)})\d+", re.I)


def is_connector_footprint(
    fp: KicadFootprint,
    prefixes: Sequence[str] = DEFAULT_CONNECTOR_PREFIXES,
) -> bool:
    """True if a footprint looks like a connector by ref prefix or footprint name."""
    if _prefix_re(prefixes).match(fp.reference):
        return True
    fp_name = fp.footprint.lower()
    return any(p.search(fp_name) for p in FOOTPRINT_PATTERNS)


def _filter_signal_pads(pads: tuple[KicadPad, ...]) -> list[KicadPad]:
    """Drop mounting holes / np_thru_holes / unnumbered pads."""
    return [
        p
        for p in pads
        if p.type not in EXCLUDED_PAD_TYPES
        and p.number != ""
        and not EXCLUDED_PAD_PREFIXES_RE.match(p.number)
    ]


def _first_non_empty_strict(props: Mapping[str, str], keys: Iterable[str]) -> str | None:
    """Match props against an explicit normalized synonym list (strict mode).

    Returns the value of the first matching key, walking ``keys`` in order.
    """
    if not props:
        return None
    normalized: dict[str, str] = {_normalize_property_key(k): v for k, v in props.items()}
    for k in keys:
        v = normalized.get(k)
        if v:
            return v
    return None


def _first_non_empty_fuzzy(props: Mapping[str, str], kind: str) -> str | None:
    """Token-classify each prop key, return first value matching ``kind``.

    ``kind`` is ``'manufacturer'`` or ``'mpn'``. See ``_classify_property_key``.
    """
    if not props:
        return None
    for k, v in props.items():
        if v and _classify_property_key(k) == kind:
            return v
    return None


def _fill_from_properties(
    conn: ExtractedConnector,
    props: Mapping[str, str],
    *,
    fuzzy: bool = False,
) -> None:
    """Fill connector manufacturer/MPN from a KiCad property bag when unset.

    With ``fuzzy=False`` (default), only keys matching an explicit synonym
    after normalization are considered. With ``fuzzy=True``, the token-based
    classifier picks up arbitrary variants (e.g. ``Distributor_Part_Number``,
    ``OEM_Manufacturer``, ``Vendor Code``).

    The same helper is called twice: once with the PCB footprint's properties
    (in :func:`extract_connectors_from_pcb`) and once with the netlist
    component's properties (in :func:`apply_netlist`). Only fields still
    ``None`` after the first call get a chance to be set by the second.
    """
    if conn.manufacturer is None:
        conn.manufacturer = (
            _first_non_empty_fuzzy(props, "manufacturer")
            if fuzzy
            else _first_non_empty_strict(props, _MFR_KEYS)
        )
    if conn.mpn is None:
        conn.mpn = (
            _first_non_empty_fuzzy(props, "mpn")
            if fuzzy
            else _first_non_empty_strict(props, _MPN_KEYS)
        )


def _enhance_with_footprint_name(conn: ExtractedConnector) -> ExtractedConnector:
    """Fill manufacturer / series / mpn / pitch / rows / mounting_style from the
    footprint name where the dataclass fields are still empty."""
    parsed = parse_footprint_name(conn.footprint)
    if conn.manufacturer is None and parsed.manufacturer is not None:
        conn.manufacturer = parsed.manufacturer
    if conn.series is None and parsed.series is not None:
        conn.series = parsed.series
    if conn.mpn is None and parsed.mpn is not None:
        conn.mpn = parsed.mpn
    if conn.pitch_mm is None and parsed.pitch_mm is not None:
        conn.pitch_mm = parsed.pitch_mm
    if conn.rows is None and parsed.rows is not None:
        conn.rows = parsed.rows
    if conn.mounting_style is None and parsed.mounting_style is not None:
        conn.mounting_style = parsed.mounting_style
    return conn


def extract_connectors_from_pcb(
    pcb: KicadPcbData,
    prefixes: Sequence[str] | None = None,
    enhance: bool = True,
    *,
    fuzzy_property_matching: bool = False,
) -> list[ExtractedConnector]:
    """Extract connector-like footprints from a parsed PCB.

    With ``enhance=True`` (default), each :class:`ExtractedConnector` is
    enriched with manufacturer / series / mpn / pitch / rows / mounting_style
    parsed from its footprint name where those fields are otherwise empty.

    With ``fuzzy_property_matching=True``, the manufacturer / MPN extraction
    from KiCad properties uses a token-based classifier instead of an explicit
    synonym list — handy for catching arbitrary user-named fields.

    Pin functions are NOT set here — call :func:`apply_netlist` after this if
    you have a netlist.
    """
    actual_prefixes: Sequence[str] = (
        prefixes if prefixes is not None else DEFAULT_CONNECTOR_PREFIXES
    )

    out: list[ExtractedConnector] = []
    for fp in pcb.footprints:
        if not is_connector_footprint(fp, actual_prefixes):
            continue
        signal_pads = _filter_signal_pads(fp.pads)
        conn = ExtractedConnector(
            reference=fp.reference,
            footprint=fp.footprint,
            value=fp.value,
            pins=[ExtractedPin(number=p.number) for p in signal_pads],
            x=fp.x,
            y=fp.y,
        )
        # PCB footprint properties carry the user's authoritative MPN /
        # manufacturer from the schematic (KiCad propagates them on update).
        _fill_from_properties(conn, fp.properties, fuzzy=fuzzy_property_matching)
        if enhance:
            _enhance_with_footprint_name(conn)
        out.append(conn)

    # Stable order: by reference (natural sort) so re-runs produce the same list.
    out.sort(key=lambda c: _natural_key(c.reference))
    return out


# ---------------------------------------------------------------------------
# Netlist application
# ---------------------------------------------------------------------------


def apply_netlist(
    connectors: Iterable[ExtractedConnector],
    netlist: KicadNetlist,
    *,
    fuzzy_property_matching: bool = False,
) -> None:
    """Set each pin's ``function`` from the netlist's net name for that pin.

    Mutates the connectors in place. Pins not present in the netlist keep
    ``function=None``. This is the v1 net-name-as-pin-function story: the
    user sees what signal each connector pin carries without the plugin
    synthesizing conductors.

    Net names are normalized via :func:`normalize_net_name` — KiCad emits
    leading slashes on hierarchical names even at root scope; we strip them
    so user-facing labels read as ``+5V`` rather than ``/+5V``.

    Also fills any ``manufacturer`` / ``mpn`` fields that are still ``None``
    from the netlist component's properties (``Manufacturer_Part_Number``,
    ``MPN``, etc.) — useful when the user populated those on the schematic
    but they didn't propagate to the PCB footprint.

    Port of ``kicadParser.ts:403-463``.
    """
    components_by_ref = {c.ref: c for c in netlist.components}
    for conn in connectors:
        ref_map = netlist.nets_by_ref.get(conn.reference)
        if ref_map:
            for pin in conn.pins:
                net_name = ref_map.get(pin.number)
                if net_name:
                    pin.function = normalize_net_name(net_name)
        if (comp := components_by_ref.get(conn.reference)) is not None:
            _fill_from_properties(conn, comp.properties, fuzzy=fuzzy_property_matching)


def normalize_net_name(name: str) -> str:
    """Strip leading slashes from a KiCad net name for user-facing display.

    KiCad's netlist exporter prefixes every net name with a slash even when
    there's no hierarchy (e.g. ``/+5V``, ``/GND``). Internal ``/``s in
    hierarchical names like ``/Power/+5V`` are preserved as ``Power/+5V``.
    """
    return name.lstrip("/")


_NAT_RE = re.compile(r"(\d+)")


def _natural_key(s: str) -> tuple:
    """`J2` < `J10`. Returns a tuple suitable for use as a sort key."""
    parts = _NAT_RE.split(s)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)
