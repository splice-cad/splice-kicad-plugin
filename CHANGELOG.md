# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] - 2026-05-08

Initial release. Exports KiCad cable-harness projects to Splice CAD.

### Added

- **Connector + jumper detection.** Auto-detects from `.kicad_pcb` by reference prefix (`J`, `CN`, `CON`, `P`, `X`) plus footprint-name regex (JST / Molex / TE / Hirose / Phoenix / generic header / socket / plug variants). Filters out mounting holes (`MP*`, `MH*`, `MTG*`), `np_thru_hole` pads, and unnumbered pads.
- **Manufacturer / MPN extraction** from KiCad symbol + footprint properties. Recognizes a long synonym list (`Manufacturer`, `Mfr`, `MFG`, `Vendor`, `Manufacturer_Part_Number`, `MPN`, `Mfr_PN`, …) with case- / space- / underscore- / hyphen-insensitive matching. Optional fuzzy classifier (default on, settings toggle) catches arbitrary `*_PART_NUMBER` / `*_MANUFACTURER_*` variants.
- **Pin functions from netlist.** Reads sibling `<project>.net` and labels each connector pin with its net name. Strips KiCad's leading-slash on hierarchical net names. Unconnected pins display as `NC`.
- **Splice CAD desktop handoff.** Plugin discovers a running desktop app via its discovery file, probes `/api/health`, and POSTs the plan over loopback (`X-Splice-Desktop-Secret` auth). Plan loads in the desktop window with no network roundtrip — works offline. Falls back to web POST if desktop isn't running.
- **Web fallback** to the configured Splice CAD backend URL. Bearer-token authentication via the `Authorization` header. Creates a real Project + project_plan owned by the authenticated user; the response includes the `open_url` for the editor.
- **Settings dialog** (`Tools → External Plugins → Splice CAD — Settings`). API key, server URL, fuzzy-property toggle, prefer-desktop toggle. Test-connection button validates against the configured server. API key is **optional** when desktop app is the user's only path.
- **Preview dialog** (`Tools → External Plugins → Export to Splice CAD`). Shows board summary, send-path status (desktop / web), per-connector list with metadata, full pin tables. Checkbox per connector to deselect from export. Send button shows the live count.
- **Auto-grid layout** for imported connectors so they land on a usable canvas. ELK auto-arrange in Splice CAD can re-flow them.
- **BOM entries** emitted alongside PlanNodes — manufacturer / MPN / spec.positions / pin labels / pin functions all populate the Splice CAD BOM panel via the `bomEntryId` linkage.
- **Stable IDs.** Re-exporting the same project produces identical node and pin IDs (UUID5 derived from the connector's reference) so the editor can recognize a re-import as an update of the same shape.
- **KiCad project name** flows through to the Splice CAD project name (sibling `.kicad_pro` filename, falling back to the board stem).
- **Toolbar icon** + Splice CAD branding throughout.

### Compatibility

- KiCad 9.0+ (uses `pcbnew.ActionPlugin`).
- Python 3.9+ (matches KiCad's bundled interpreter).

### Known limitations

- The `Splice_*` symbol-annotation override fields (`Splice_Skip`, `Splice_Part`, `Splice_Ref`, `Splice_Pin_Map`, `Splice_Group`, `Splice_Twisted`) are documented in RFC-003 §4.5 but not yet implemented. Tracked for v0.1.0.
- Re-exporting the same project always creates a new Splice CAD project. Dedupe-by-`external_id` is planned for v0.1.0.
- Hierarchical schematics are supported via the netlist (post-elaboration) but not by parsing `.kicad_sch` directly.
- Schematic raw `.kicad_sch` parsing isn't shipped — the plugin reads PCB footprints + netlist properties.

### Internal

- 237 unit tests covering parser, detector, builder, client, config, and dialog helpers.
- Hand-rolled S-expression parser ported byte-for-byte from the Splice CAD frontend's `kicadParser.ts` (drift-checked via shared `kicad-detect.json`).
- Stdlib-only HTTP (`urllib.request`); no `requests` or other pip-installable deps to satisfy KiCad PCM's no-runtime-pip rule.

[Unreleased]: https://github.com/splice-cad/splice-kicad-plugin/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/splice-cad/splice-kicad-plugin/releases/tag/v0.0.1
