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

    print(f"wrote PCM repo files to {out}/ for v{version}")
    print(f"  add-repository URL: {base_url}/repository.json")


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
