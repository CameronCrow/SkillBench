"""Vendor the pinned plugins into .cache/ and record the pins.

Usage (on the machine that has network access / the marketplace cache):

    python -m harness.vendor --solidifier-ref <sha-or-tag> \
        --ponytail-source <path-to-marketplace-cache-copy> \
        --ponytail-version <version-string>

Solidifier is cloned from GitHub and checked out at the given ref; the
resolved commit SHA is recorded. Ponytail has no public clone URL, so it is
copied from a local path (your marketplace cache) and pinned by a recorded
version string plus a content hash of the copied tree. Both pins land in
.cache/vendor.json, which harness/run.py embeds into every run's metadata.

Re-running is idempotent: existing .cache/ copies are replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .common import CACHE_DIR, PLUGIN_DIRS, VENDOR_MANIFEST

SOLIDIFIER_URL = "https://github.com/FernandoJRR/solidifier"


def tree_hash(root: Path) -> str:
    """Deterministic content hash of a directory tree (paths + bytes)."""
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def vendor_solidifier(ref: str) -> dict:
    dest = CACHE_DIR / "solidifier"
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", SOLIDIFIER_URL, str(dest)], check=True)
    subprocess.run(["git", "checkout", ref], cwd=dest, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, check=True,
                         capture_output=True, text=True).stdout.strip()
    plugin_dir = PLUGIN_DIRS["solidifier"]
    if not plugin_dir.is_dir():
        sys.exit(f"clone succeeded but plugin dir not found: {plugin_dir}\n"
                 "(--plugin-dir must point at claude-code/plugins/solidifier "
                 "inside the clone — has the repo layout changed?)")
    return {"url": SOLIDIFIER_URL, "requested_ref": ref, "commit": sha}


def vendor_ponytail(source: Path, version: str) -> dict:
    dest = PLUGIN_DIRS["ponytail"]
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return {"source": str(source), "version": version, "tree_sha256": tree_hash(dest)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solidifier-ref", help="commit SHA or tag to pin solidifier at")
    ap.add_argument("--ponytail-source", type=Path,
                    help="local path to the ponytail plugin dir to copy")
    ap.add_argument("--ponytail-version", help="version string to record for ponytail")
    args = ap.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)
    manifest = json.loads(VENDOR_MANIFEST.read_text()) if VENDOR_MANIFEST.exists() else {}

    if args.solidifier_ref:
        manifest["solidifier"] = vendor_solidifier(args.solidifier_ref)
        print(f"solidifier pinned at {manifest['solidifier']['commit']}")
    if args.ponytail_source:
        if not args.ponytail_version:
            sys.exit("--ponytail-source requires --ponytail-version")
        if not args.ponytail_source.is_dir():
            sys.exit(f"not a directory: {args.ponytail_source}")
        manifest["ponytail"] = vendor_ponytail(args.ponytail_source, args.ponytail_version)
        print(f"ponytail {args.ponytail_version} copied "
              f"(tree {manifest['ponytail']['tree_sha256'][:12]}…)")
    if not (args.solidifier_ref or args.ponytail_source):
        ap.error("nothing to do — pass --solidifier-ref and/or --ponytail-source")

    VENDOR_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest written: {VENDOR_MANIFEST}")


if __name__ == "__main__":
    main()
