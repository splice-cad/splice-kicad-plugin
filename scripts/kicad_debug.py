"""Diagnostic script — run inside KiCad's PCB Editor scripting console.

Usage (paste this single line into Tools -> Scripting Console):

    exec(open("/Users/djstrickland/GitHub/splice-kicad-plugin/scripts/kicad_debug.py").read())
"""

import sys
import traceback

print("=" * 60)
print("Splice plugin diagnostic")
print("=" * 60)

# 1. sys.path entries that might host the plugin
print("\n[1] sys.path entries mentioning 'splice', '3rdparty', or 'scripting':")
for p in sys.path:
    if any(needle in p.lower() for needle in ("splice", "3rdparty", "scripting")):
        print("    " + p)

# 2. Import the package
print("\n[2] import splice_kicad_plugin")
try:
    import splice_kicad_plugin
    print("    OK version=" + splice_kicad_plugin.__version__)
    print("    file=" + splice_kicad_plugin.__file__)
except Exception:
    traceback.print_exc()
    print("    -> stop here, the package isn't on sys.path or has an import error")
else:
    # 3. Action plugin module
    print("\n[3] from splice_kicad_plugin.ui import action_plugin")
    try:
        from splice_kicad_plugin.ui import action_plugin
        has_class = hasattr(action_plugin, "SpliceExportPlugin")
        print("    OK loaded; SpliceExportPlugin defined: " + str(has_class))
        if not has_class:
            print("    -> the 'if pcbnew is not None' guard didn't fire; pcbnew import")
            print("       failed inside action_plugin even though we're in pcbnew?")
    except Exception:
        traceback.print_exc()

    # 4. Did our plugin actually register with KiCad's plugin manager?
    print("\n[4] pcbnew.ActionPlugins registered:")
    try:
        import pcbnew
        names = []
        # KiCad doesn't expose a Python-side "list registered plugins" API directly,
        # but ActionPlugin instances live in pcbnew.GetWizardsBackTrace / similar.
        # The most reliable check: invoke our plugin class directly and see if the
        # dialog comes up.
        from splice_kicad_plugin.ui.action_plugin import SpliceExportPlugin  # noqa: F401
        print("    OK SpliceExportPlugin class is importable")
        print("    -> if the menu still doesn't show, try:")
        print("       Tools -> External Plugins -> Refresh Plugins")
    except Exception:
        traceback.print_exc()

print("\n" + "=" * 60)
print("Paste everything above this line back to Claude.")
print("=" * 60)
