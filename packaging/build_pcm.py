"""Build a KiCad PCM-compatible zip from the plugin source tree.

Layout produced::

    splice-kicad-plugin-<version>.zip
      ├── metadata.json
      ├── plugins/
      │     └── splice_kicad_plugin/    # importable package; KiCad adds plugins/ to sys.path
      └── resources/                    # icons etc. (empty for now)

Usage::

    python3 packaging/build_pcm.py --version 0.0.1
    python3 packaging/build_pcm.py --version 0.0.1 --output dist/
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build(version: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = REPO_ROOT / "packaging" / "build" / f"staging-{version}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # plugins/  — package contents go here directly. Per the KiCad PCM addon
    # spec, "Place your plugin directly inside the `plugins` subdirectory, not
    # inside a second level of subdirectory." So we copy the *contents* of
    # splice_kicad_plugin/ into plugins/, not the directory itself. Internal
    # imports are relative so the package works under any outer name.
    plugins_dir = staging / "plugins"
    shutil.copytree(
        REPO_ROOT / "splice_kicad_plugin",
        plugins_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_vendor"),
    )

    # resources/  — PCM display icon (64x64) shown in the Plugin and Content
    # Manager listing.
    resources_src = REPO_ROOT / "resources"
    resources_dst = staging / "resources"
    if resources_src.is_dir():
        shutil.copytree(resources_src, resources_dst)
    else:
        resources_dst.mkdir()

    # metadata.json — patch in the build version unless --version is the dev sentinel.
    src_meta = json.loads((REPO_ROOT / "metadata" / "metadata.json").read_text())
    if version != "0.0.0-dev":
        src_meta["versions"][0]["version"] = version
    # The metadata.json *inside the package* must not carry repository-level
    # distribution fields — a package can't contain its own download hash, and
    # KiCad's official PCM validator rejects `download_sha256` in the in-zip
    # metadata. Those fields are assigned by the repository, not the package.
    for ver in src_meta.get("versions", []):
        for repo_field in (
            "download_sha256",
            "download_url",
            "download_size",
            "install_size",
        ):
            ver.pop(repo_field, None)
    (staging / "metadata.json").write_text(json.dumps(src_meta, indent=2) + "\n")

    zip_path = output_dir / f"splice-kicad-plugin-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(staging))

    return zip_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True, help="semver string for the build")
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "dist",
        help="directory the zip is written to",
    )
    args = p.parse_args(argv)
    zip_path = build(args.version, args.output)
    print(f"built {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
