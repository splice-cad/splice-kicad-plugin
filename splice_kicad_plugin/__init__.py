"""Splice CAD — KiCad plugin.

Exports wired cable-harness plans from KiCad to Splice CAD.

See ``docs/RFC-003-KICAD-PLUGIN.md`` in the main splice repo for architecture.
"""

from __future__ import annotations  # PEP 563 — Py 3.9 compat (KiCad ships Python 3.9)

from .errors import SpliceError
from .version import PCM_IDENTIFIER, SCHEMA_VERSION, __version__

__all__ = ["PCM_IDENTIFIER", "SCHEMA_VERSION", "SpliceError", "__version__"]

# When loaded inside KiCad's pcbnew, register the action plugin so it appears
# under Tools → External Plugins. Outside KiCad (tests, CI, headless CLI),
# pcbnew isn't importable and we silently skip registration.
#
# Imports are relative so this package works under any outer name — both as
# `splice_kicad_plugin` (dev / local-install) and as `plugins` (after PCM
# extracts the zip into `<identifier>/plugins/`).
try:
    import pcbnew  # type: ignore[import-not-found]  # noqa: F401
except ImportError:
    pass
else:
    from .ui import action_plugin  # noqa: F401  -- registers on import
