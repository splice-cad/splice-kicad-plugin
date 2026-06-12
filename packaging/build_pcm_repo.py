"""Generate release metadata + a self-hosted KiCad PCM repository from a built zip.

Given the already-built plugin zip (see ``build_pcm.py``), this emits, into an
output directory, everything needed to publish a release:

    <out>/
      metadata.json      # single-package metadata, sha/size filled — for the
                         # official KiCad PCM merge request (gitlab.com/kicad/addons/metadata)
      packages.json      # { "packages": [ <metadata> ] }    — self-hosted PCM repo
      resources.zip      # <identifier>/icon.png (64x64)      — self-hosted PCM repo
      repository.json    # top-level index pointing at packages.json + resources.zip,
                         # with their sha256 + timestamps    — self-hosted PCM repo

Users add the hosted ``repository.json`` URL in KiCad: PCM -> Manage
Repositories -> "+". The sha256/size values come from the zip passed in, so the
published artifact and the metadata can never drift (see the CI determinism note
in the release workflow).

Usage::

    python3 packaging/build_pcm_repo.py \
      --version 0.0.1 \
      --zip dist/splice-kicad-plugin-0.0.1.zip \
      --download-url https://github.com/splice-cad/splice-kicad-plugin/releases/download/v0.0.1/splice-kicad-plugin-0.0.1.zip \
      --base-url https://splice-cad.github.io/splice-kicad-plugin \
      --out pcm-repo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_size(zip_path: Path) -> int:
    """Total uncompressed bytes of the zip's regular files (PCM's install size)."""
    with zipfile.ZipFile(zip_path) as z:
        return sum(i.file_size for i in z.infolist() if not i.is_dir())


def _timestamps() -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp())


def build(
    version: str, zip_path: Path, download_url: str, base_url: str, out: Path
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/")

    pkg = json.loads((REPO_ROOT / "metadata" / "metadata.json").read_text())
    identifier = pkg["identifier"]
    pkg.pop("$schema", None)  # $schema belongs on the top-level repo files, not the package

    # Fill the matching version entry with the real artifact facts.
    matched = False
    for ver in pkg.get("versions", []):
        if ver.get("version") == version:
            ver["download_url"] = download_url
            ver["download_sha256"] = _sha256(zip_path)
            ver["download_size"] = zip_path.stat().st_size
            ver["install_size"] = _install_size(zip_path)
            matched = True
    if not matched:
        raise SystemExit(
            f"version {version!r} not found in metadata.json versions[]"
        )

    # 1) metadata.json — single-package, for the official KiCad PCM MR.
    meta_out = {"$schema": "https://go.kicad.org/pcm/schemas/v1", **pkg}
    (out / "metadata.json").write_text(json.dumps(meta_out, indent=2) + "\n")

    # 2) packages.json — self-hosted repo package list.
    packages = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "packages": [pkg],
    }
    (out / "packages.json").write_text(json.dumps(packages, indent=2) + "\n")

    # 3) resources.zip — <identifier>/icon.png (64x64), shown in the PCM listing.
    icon = REPO_ROOT / "resources" / "icon.png"
    resources_zip = out / "resources.zip"
    with zipfile.ZipFile(resources_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(icon, f"{identifier}/icon.png")

    # 4) repository.json — top-level index with sha256 + timestamps for both files.
    pkg_time, pkg_ts = _timestamps()
    res_time, res_ts = pkg_time, pkg_ts
    repository = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "name": "Splice CAD KiCad plugin repository",
        "maintainer": pkg["maintainer"],
        "packages": {
            "url": f"{base_url}/packages.json",
            "sha256": _sha256(out / "packages.json"),
            "update_time_utc": pkg_time,
            "update_timestamp": pkg_ts,
        },
        "resources": {
            "url": f"{base_url}/resources.zip",
            "sha256": _sha256(resources_zip),
            "update_time_utc": res_time,
            "update_timestamp": res_ts,
        },
    }
    (out / "repository.json").write_text(json.dumps(repository, indent=2) + "\n")

    # 5) index.html — a friendly landing page so the Pages root isn't a bare 404.
    (out / "index.html").write_text(_index_html(pkg, f"{base_url}/repository.json"))

    print(f"wrote PCM repo files to {out}/ for v{version}")
    print(f"  add-repository URL: {base_url}/repository.json")


def _index_html(pkg: dict, add_url: str) -> str:
    """A small self-contained landing page for the PCM repository root."""
    name = pkg.get("name", "Splice CAD")
    desc = pkg.get("description", "")
    res = pkg.get("resources", {})
    repo = res.get("repository", "https://github.com/splice-cad/splice-kicad-plugin")
    docs = res.get("documentation", "https://splice-cad.com")
    home = res.get("homepage", "https://splice-cad.com")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — KiCad Plugin Repository</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:#1e1e1e; color:rgba(255,255,255,.87);
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:680px; margin:0 auto; padding:48px 24px; }}
  h1 {{ font-size:28px; margin:0 0 8px; }}
  p.lead {{ color:rgba(255,255,255,.6); margin-top:0; }}
  h2 {{ font-size:18px; margin:32px 0 8px; }}
  code,kbd {{ background:#2a2a2a; border:1px solid rgba(255,255,255,.1);
    border-radius:4px; padding:2px 6px; font-size:14px; }}
  .url {{ display:block; background:#2a2a2a; border:1px solid rgba(255,255,255,.15);
    border-radius:6px; padding:12px 14px; margin:8px 0 4px; font-family:ui-monospace,monospace;
    font-size:14px; word-break:break-all; user-select:all; }}
  ol {{ padding-left:20px; }} li {{ margin:6px 0; }}
  a {{ color:#5aa1ff; }}
  footer {{ margin-top:40px; padding-top:16px; border-top:1px solid rgba(255,255,255,.1);
    color:rgba(255,255,255,.4); font-size:14px; }}
</style>
</head>
<body><main>
  <h1>{name}</h1>
  <p class="lead">{desc}</p>

  <h2>Install in KiCad</h2>
  <p>Add this repository in KiCad's <strong>Plugin and Content Manager</strong>:</p>
  <span class="url">{add_url}</span>
  <ol>
    <li>KiCad &rarr; <strong>Plugin and Content Manager</strong> &rarr; <strong>Manage</strong> &rarr; <strong>Repositories</strong>.</li>
    <li>Add the URL above (name it "Splice CAD"), then select it in the repository dropdown.</li>
    <li>Choose <strong>{name}</strong> &rarr; <strong>Install</strong> &rarr; <strong>Apply Pending Changes</strong>.</li>
    <li>In the PCB Editor: <kbd>Tools &rarr; External Plugins &rarr; Export to Splice CAD</kbd>.</li>
  </ol>
  <p>Or download the <code>.zip</code> from <a href="{repo}/releases">Releases</a> and use
     <strong>Install from File</strong>.</p>

  <footer>
    <a href="{docs}">Documentation</a> &nbsp;·&nbsp;
    <a href="{repo}">GitHub</a> &nbsp;·&nbsp;
    <a href="{home}">splice-cad.com</a>
  </footer>
</main></body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--zip", required=True, type=Path)
    p.add_argument("--download-url", required=True)
    p.add_argument("--base-url", required=True, help="GitHub Pages base URL of this repo")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "pcm-repo")
    args = p.parse_args(argv)
    build(args.version, args.zip, args.download_url, args.base_url, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
