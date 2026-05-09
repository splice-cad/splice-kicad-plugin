"""Footprint-name parser — extract MPN/manufacturer/series/pitch/pincount.

Direct port of ``footprintParser.ts:24-261`` from the splice frontend, **minus**
the scoring algorithm (``calculateMatchConfidence``, ``generateMatingSearchQuery``)
and the ``confidence`` field on ``ParsedFootprint``. The plugin doesn't score
(RFC-003 §3 — part matching is a server-side concern handled by the user in-app);
the parsed fields are carried as node ``meta``.

KiCad naming convention (KLC F1.2):

    [Category]_[Manufacturer]_[Series]_[MPN]_[Pins]x[Rows]_P[Pitch]mm_[Modifiers]

Example::

    Connector_JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Known manufacturers and series
# ---------------------------------------------------------------------------

KNOWN_MANUFACTURERS: dict[str, str] = {
    "jst": "JST",
    "molex": "Molex",
    "te": "TE Connectivity",
    "amp": "TE Connectivity",
    "tyco": "TE Connectivity",
    "samtec": "Samtec",
    "amphenol": "Amphenol",
    "hirose": "Hirose",
    "phoenix": "Phoenix Contact",
    "phoenixcontact": "Phoenix Contact",
    "wago": "WAGO",
    "harting": "HARTING",
    "wurth": "Wurth Elektronik",
    "wuerth": "Wurth Elektronik",
    "mill": "Mill-Max",
    "millmax": "Mill-Max",
    "sullins": "Sullins",
    "fci": "FCI",
    "harwin": "Harwin",
    "adam": "Adam Tech",
    "weidmuller": "Weidmuller",
    "on_shore": "On Shore",
    "onshore": "On Shore",
    "cui": "CUI Devices",
    "kycon": "Kycon",
}


@dataclass(frozen=True)
class _SeriesInfo:
    normalized: str
    manufacturer: str | None = None
    typical_pitch: float | None = None


KNOWN_SERIES: dict[str, _SeriesInfo] = {
    # JST
    "xh": _SeriesInfo("XH", "JST", 2.5),
    "ph": _SeriesInfo("PH", "JST", 2.0),
    "sh": _SeriesInfo("SH", "JST", 1.0),
    "gh": _SeriesInfo("GH", "JST", 1.25),
    "zh": _SeriesInfo("ZH", "JST", 1.5),
    "eh": _SeriesInfo("EH", "JST", 2.5),
    "vh": _SeriesInfo("VH", "JST", 3.96),
    "pa": _SeriesInfo("PA", "JST", 2.0),
    # Molex
    "microfit": _SeriesInfo("Micro-Fit 3.0", "Molex", 3.0),
    "micro-fit": _SeriesInfo("Micro-Fit 3.0", "Molex", 3.0),
    "minifit": _SeriesInfo("Mini-Fit Jr", "Molex", 4.2),
    "mini-fit": _SeriesInfo("Mini-Fit Jr", "Molex", 4.2),
    "nanofit": _SeriesInfo("Nano-Fit", "Molex", 2.5),
    "nano-fit": _SeriesInfo("Nano-Fit", "Molex", 2.5),
    "picoblade": _SeriesInfo("PicoBlade", "Molex", 1.25),
    "clik": _SeriesInfo("CLIK-Mate", "Molex"),
    "kk": _SeriesInfo("KK", "Molex", 2.54),
    "sabre": _SeriesInfo("Sabre", "Molex"),
    "mlx": _SeriesInfo("MLX", "Molex"),
    "megafit": _SeriesInfo("Mega-Fit", "Molex", 5.7),
    "ultrafit": _SeriesInfo("Ultra-Fit", "Molex", 3.5),
    # TE / AMP
    "mta": _SeriesInfo("MTA-100", "TE Connectivity", 2.54),
    "mta-100": _SeriesInfo("MTA-100", "TE Connectivity", 2.54),
    "mta-156": _SeriesInfo("MTA-156", "TE Connectivity", 3.96),
    "ampmodu": _SeriesInfo("AMPMODU", "TE Connectivity"),
    "micromate": _SeriesInfo("Micro-MaTch", "TE Connectivity", 1.27),
    "minipv": _SeriesInfo("Mini-PV", "TE Connectivity"),
    "val_u_lok": _SeriesInfo("Val-U-Lok", "TE Connectivity"),
    # Samtec
    "ftsh": _SeriesInfo("FTSH", "Samtec", 1.27),
    "esq": _SeriesInfo("ESQ", "Samtec", 2.54),
    "ssq": _SeriesInfo("SSQ", "Samtec", 2.54),
    "tsw": _SeriesInfo("TSW", "Samtec", 2.54),
    "ssm": _SeriesInfo("SSM", "Samtec", 2.54),
    "tmm": _SeriesInfo("TMM", "Samtec", 2.0),
    "clte": _SeriesInfo("CLTE", "Samtec", 0.635),
    # Phoenix Contact
    "mc": _SeriesInfo("MC", "Phoenix Contact", 3.5),
    "mstb": _SeriesInfo("MSTB", "Phoenix Contact", 5.0),
    "mkds": _SeriesInfo("MKDS", "Phoenix Contact", 5.0),
    "ptfix": _SeriesInfo("PTFIX", "Phoenix Contact"),
    "combicon": _SeriesInfo("COMBICON", "Phoenix Contact"),
    # Hirose
    "df13": _SeriesInfo("DF13", "Hirose", 1.25),
    "df11": _SeriesInfo("DF11", "Hirose", 2.0),
    "df12": _SeriesInfo("DF12", "Hirose", 0.5),
    "df14": _SeriesInfo("DF14", "Hirose", 1.25),
    # Generic types
    "pinheader": _SeriesInfo("Pin Header"),
    "pinsocket": _SeriesInfo("Pin Socket"),
    "header": _SeriesInfo("Header"),
    "dsub": _SeriesInfo("D-Sub"),
    "d-sub": _SeriesInfo("D-Sub"),
    "usb": _SeriesInfo("USB"),
    "rj45": _SeriesInfo("RJ45"),
    "rj11": _SeriesInfo("RJ11"),
    "barrel": _SeriesInfo("Barrel Jack"),
    "screw_terminal": _SeriesInfo("Screw Terminal"),
    "idc": _SeriesInfo("IDC"),
}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


Gender = Literal["male", "female"]


@dataclass
class ParsedFootprint:
    """Whatever metadata we could pull from a KiCad footprint name.

    All optional fields are ``None`` when not detectable. The ``raw`` field
    is always populated with the original input.
    """

    raw: str
    manufacturer: str | None = None
    series: str | None = None
    mpn: str | None = None
    pin_count: int | None = None
    rows: int | None = None
    pitch_mm: float | None = None
    mounting_style: str | None = None
    gender: Gender | None = None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_PITCH_RE = re.compile(r"[_\-]P(\d+(?:\.\d+)?)\s*mm", re.I)
_PIN_LAYOUT_RE = re.compile(r"(\d+)x(\d+)")
_MPN_PART_RE = re.compile(r"[A-Z]{1,3}\d{1,2}[A-Z]?[-_]?[A-Z0-9]+[-_]?[A-Z0-9]*", re.I)
_MPN_PIN_LAYOUT_FULL_RE = re.compile(r"^\d+x\d+$")
_MPN_PITCH_FULL_RE = re.compile(r"^p\d", re.I)

_GENDER_MALE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmale\b", re.I),
    re.compile(r"\bplug\b", re.I),
    re.compile(r"\bheader\b", re.I),
)
_GENDER_FEMALE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfemale\b", re.I),
    re.compile(r"\breceptacle\b", re.I),
    re.compile(r"\bsocket\b", re.I),
)

_GENERIC_SKIP_PARTS: frozenset[str] = frozenset(
    {"connector", "conn", "header", "socket", "vertical", "horizontal", "smd"}
)

# Order matters — first match wins, faithful to footprintParser.ts:184-188.
_MOUNTING_STYLE_TOKENS: tuple[str, ...] = (
    "vertical",
    "horizontal",
    "angled",
    "smd",
    "tht",
    "throughhole",
    "rightangle",
    "ra",
)
_MOUNTING_STYLE_NORMALIZE: dict[str, str] = {
    "tht": "Through-Hole",
    "throughhole": "Through-Hole",
    "smd": "SMD",
    "rightangle": "Right-Angle",
    "ra": "Right-Angle",
}


def parse_footprint_name(footprint: str) -> ParsedFootprint:
    """Parse a KiCad footprint name and extract whatever metadata we can.

    Empty input returns a sparse :class:`ParsedFootprint` with everything
    ``None`` except ``raw``.
    """
    result = ParsedFootprint(raw=footprint)
    if not footprint:
        return result

    # KiCad uses ":" for library:footprint and "_" between fields.
    normalized = footprint.replace(":", "_").lower()
    parts = normalized.split("_")

    # Pitch (P2.54mm, P2.50mm, …)
    m = _PITCH_RE.search(footprint)
    if m:
        try:
            result.pitch_mm = float(m.group(1))
        except ValueError:
            pass

    # Pin layout (1x04, 2x10, …)
    m = _PIN_LAYOUT_RE.search(footprint)
    if m:
        try:
            rows = int(m.group(1))
            cols = int(m.group(2))
            result.rows = rows
            result.pin_count = rows * cols
        except ValueError:
            pass

    # Mounting style — first substring hit wins.
    for style in _MOUNTING_STYLE_TOKENS:
        if style in normalized:
            result.mounting_style = _MOUNTING_STYLE_NORMALIZE.get(style, style.capitalize())
            break

    # Gender — male hints first; only check female if no male hint matched.
    for pat in _GENDER_MALE_RES:
        if pat.search(footprint):
            result.gender = "male"
            break
    if result.gender is None:
        for pat in _GENDER_FEMALE_RES:
            if pat.search(footprint):
                result.gender = "female"
                break

    # Manufacturer — first part that's a known manufacturer key.
    for part in parts:
        mfr = KNOWN_MANUFACTURERS.get(part)
        if mfr is not None:
            result.manufacturer = mfr
            break

    # Series — first part that's a known series key. Series may carry an
    # implicit manufacturer + typical pitch; only fill in if not already set.
    for part in parts:
        info = KNOWN_SERIES.get(part)
        if info is not None:
            result.series = info.normalized
            if result.manufacturer is None and info.manufacturer is not None:
                result.manufacturer = info.manufacturer
            if result.pitch_mm is None and info.typical_pitch is not None:
                result.pitch_mm = info.typical_pitch
            break

    # MPN — first part that looks like a part number, after skipping known
    # category, manufacturer, series, layout, and pitch tokens.
    for part in parts:
        if part in _GENERIC_SKIP_PARTS:
            continue
        if part in KNOWN_MANUFACTURERS or part in KNOWN_SERIES:
            continue
        if _MPN_PIN_LAYOUT_FULL_RE.match(part):
            continue
        if _MPN_PITCH_FULL_RE.match(part):
            continue
        if len(part) > 3 and _MPN_PART_RE.search(part):
            result.mpn = part.upper()
            break

    return result
