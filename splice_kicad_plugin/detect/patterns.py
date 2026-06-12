"""Single-source loader for connector-detection regexes.

Reads ``<package>/shared/kicad-detect.json``. The Splice frontend's in-browser
KiCad import is intended to consume the same JSON via a git submodule (see
``RFC-003e`` §4) so a regex change here ships with both sides in lockstep.

Path resolution uses ``Path(__file__)`` so the loader works regardless of the
outer package name — both ``splice_kicad_plugin`` (dev) and ``plugins`` (after
PCM extract).
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat

import json
import re
from pathlib import Path

_CFG = json.loads(
    (Path(__file__).resolve().parent.parent / "shared" / "kicad-detect.json").read_text(
        encoding="utf-8"
    )
)

DEFAULT_CONNECTOR_PREFIXES: tuple[str, ...] = tuple(_CFG["prefixes"])

FOOTPRINT_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.I) for p in _CFG["footprintPatterns"]
)

LIB_ID_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.I) for p in _CFG["libIdPatterns"])

EXCLUDED_PAD_TYPES: frozenset = frozenset(_CFG["excludedPadTypes"])

EXCLUDED_PAD_PREFIXES_RE: re.Pattern = re.compile(
    rf"^({'|'.join(_CFG['excludedPadPrefixes'])})",
    re.I,
)
