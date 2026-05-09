"""Detect submodule — connector identification + footprint name parsing."""

from .connectors import (
    ExtractedConnector,
    ExtractedPin,
    apply_netlist,
    extract_connectors_from_pcb,
    is_connector_footprint,
    normalize_net_name,
)
from .footprint_name import (
    KNOWN_MANUFACTURERS,
    KNOWN_SERIES,
    ParsedFootprint,
    parse_footprint_name,
)
from .patterns import (
    DEFAULT_CONNECTOR_PREFIXES,
    EXCLUDED_PAD_PREFIXES_RE,
    EXCLUDED_PAD_TYPES,
    FOOTPRINT_PATTERNS,
    LIB_ID_PATTERNS,
)

__all__ = [
    "DEFAULT_CONNECTOR_PREFIXES",
    "EXCLUDED_PAD_PREFIXES_RE",
    "EXCLUDED_PAD_TYPES",
    "ExtractedConnector",
    "ExtractedPin",
    "FOOTPRINT_PATTERNS",
    "KNOWN_MANUFACTURERS",
    "KNOWN_SERIES",
    "LIB_ID_PATTERNS",
    "ParsedFootprint",
    "apply_netlist",
    "extract_connectors_from_pcb",
    "is_connector_footprint",
    "normalize_net_name",
    "parse_footprint_name",
]
