# Splice CAD — KiCad Plugin

Export wired cable-harness designs from KiCad to [Splice CAD](https://splice-cad.com) in one click.

The plugin extracts your project's connectors plus their pin-to-net mappings, attaches manufacturer / MPN data from your symbol fields, and pushes the resulting plan straight to Splice CAD. If the Splice CAD desktop app is running, the plan loads locally with no network roundtrip; otherwise it posts to your account on splice-cad.com.

## Requirements

- **KiCad 9.x** (primary target) — also runs on KiCad 10.x.
- A **Splice CAD account** ([sign up free](https://splice-cad.com)). The API key is only required when not using the desktop app.

## Installation

### Via KiCad's Plugin and Content Manager (recommended, once listed)

`Tools → Plugin and Content Manager → Plugins → Splice CAD → Install`

### Install from File (current)

1. Download `splice-kicad-plugin-<version>.zip` from the [latest release](https://github.com/splice-cad/splice-kicad-plugin/releases).
2. KiCad → `Tools → Plugin and Content Manager → Install from File…` → select the zip.
3. Restart KiCad.

## Setup

The plugin has two send paths and you only need to configure one:

**Option A — Splice CAD desktop app (no API key needed).** If you already use the [Splice CAD desktop app](https://splice-cad.com), launch it and skip to Usage. The plugin discovers it automatically over a local listener.

**Option B — Web (splice-cad.com or self-hosted backend).** Sign in to your Splice CAD account, open `Account → API Key`, click **Generate**. In KiCad's PCB Editor: `Tools → External Plugins → Splice CAD — Settings`, paste the key, click **Test connection**, click **Save**.

You can have both configured — the plugin prefers the desktop app when it's running and falls back to the web URL when it isn't.

## Usage

In the PCB Editor: `Tools → External Plugins → Export to Splice CAD`.

The preview dialog shows:

- Each detected connector with its part metadata (manufacturer, series, MPN, pitch).
- Pin-by-pin function names pulled from your netlist (e.g. `Pin 1  +5V`, `Pin 2  GND`, `Pin 3  NC`).
- The destination — desktop app, web URL, or both.

Uncheck any connectors you don't want to send, then click **Send to Splice CAD (N)**. The plan opens in your Splice CAD desktop window (or the URL is shown for the web path).

### Generating the netlist

For pin-function labels (`+5V`, `GND`, `CAN_H`, …) the plugin reads `<project>.net` next to your `.kicad_pcb`. Generate it once with:

```bash
kicad-cli sch export netlist <project>.kicad_sch -o <project>.net
```

If the file isn't there, pin functions show as `NC` and the connectors still export.

## Symbol annotation conventions

The plugin auto-detects connectors by reference prefix (`J`, `CN`, `CON`, `P`, `X`) and by footprint-name regex (`connector_*`, `jst_*`, `molex_*`, `header`, `socket`, etc.).

It pulls **manufacturer** and **MPN** from your KiCad symbol fields with a fuzzy classifier — these all work:

| Field name in your symbol                                        | Recognized as |
|---|---|
| `Manufacturer`, `MFR`, `Mfg`, `Vendor`, `Maker`                  | manufacturer |
| `MANUFACTURER_NAME`, `Mfr_Name`, `Mfg Name`                      | manufacturer |
| `Manufacturer_Part_Number`, `MPN`, `Mfr_PN`, `Part Number`, `PN` | MPN |
| `Distributor_Part_Number`, `Mouser Part Number`, `OEM_PartNum`   | MPN |

Strict matching (no fuzzy) is available in Settings if you want predictable behavior.

### Planned overrides (not yet shipped)

| Field | Scope | Purpose |
|---|---|---|
| `Splice_Skip` | symbol | Force-exclude a symbol that would otherwise match |
| `Splice_Part` | symbol | Pin to a specific Splice CAD part SKU |
| `Splice_Ref` | symbol | Stable connector ID across re-exports |
| `Splice_Pin_Map` | symbol | Inline pin renames (`1=A,2=B`) for keyed connectors |
| `Splice_Group` | netclass | Group netclass members as a wire group |
| `Splice_Twisted` | netclass | Mark a `Splice_Group` as a twisted pair |

## Local development install

Symlink the package into KiCad's user scripting plugins directory; KiCad picks it up at next launch.

**macOS (KiCad 10.x):**
```bash
ln -s "$PWD/splice_kicad_plugin" \
  ~/Documents/KiCad/10.0/3rdparty/plugins/splice_kicad_plugin
```

**Linux:** `~/.local/share/kicad/10.0/3rdparty/plugins/`
**Windows:** `%APPDATA%\kicad\10.0\3rdparty\plugins\`

Then `Cmd+Q` and relaunch KiCad. The plugin's PCB Editor menu entries appear under `Tools → External Plugins`.

To pick up code changes, save the file and re-run the plugin from the menu — KiCad re-imports the module each invocation.

### Running the test suite

```bash
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/pytest tests/ -v
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
