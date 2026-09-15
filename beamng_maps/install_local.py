"""One command from a checkout to the six maps installed in your BeamNG.drive.

    python beamng_maps/install_local.py                      # build from public data, then deploy
    python beamng_maps/install_local.py --parts <folder>     # rejoin delivered parts instead of building
    python beamng_maps/install_local.py --maps meteor_crater black_bear_pass
    python beamng_maps/install_local.py --no-deploy          # stop after the dist ZIPs exist

For every map it makes sure ``<map>/dist/<key>_ericrolph.zip`` exists and matches its lock:
from delivered parts when ``--parts`` names a folder that holds them (verified against
``SHA256SUMS.txt``), otherwise by running the pipeline (fetch -> terrain -> level -> dist;
about 3 GB of public downloads the first time, cached after that). Then it runs
``deploy_local.py --deploy``, which copies the ZIPs into
``%LOCALAPPDATA%\\BeamNG\\BeamNG.drive\\current\\mods`` and re-hashes them. Close BeamNG first;
the deploy step refuses to swap files under a running game.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent


def _load(name: str):
    loader = importlib.util.spec_from_file_location(f"beamng_maps_{name}", PACK_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(loader)
    sys.modules[loader.name] = module
    loader.loader.exec_module(module)
    return module


build = _load("build")
join_parts = _load("join_parts")
deploy_local = _load("deploy_local")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_ok(key: str) -> bool:
    spec = build.load_spec(key)
    dist = build.PACK_ROOT / key / "dist"
    zip_path = dist / spec.ZIP_BASENAME
    lock_path = dist / f"{spec.MOD_ID}.lock.json"
    if not zip_path.is_file() or not lock_path.is_file():
        return False
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    return sha256_file(zip_path) == lock["sha256"]


def ensure_release(key: str, *, force: bool) -> None:
    if release_ok(key) and not force:
        print(f"== {key}: release present and matches its lock")
        return
    started = time.time()
    for stage in ("fetch", "terrain", "level", "dist"):
        build.run_stage(key, stage, force=False)
    print(f"== {key}: built in {(time.time() - started) / 60:.1f} min")
    if not release_ok(key):
        raise SystemExit(f"{key}: build finished but the dist ZIP does not match its lock")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", type=Path, help="folder holding <key>_ericrolph.zip.partN files + SHA256SUMS.txt")
    parser.add_argument("--maps", nargs="*", help="map keys to install (default: every map in the pack)")
    parser.add_argument("--no-deploy", action="store_true", help="stop once the dist ZIPs exist")
    parser.add_argument("--force-rebuild", action="store_true", help="rebuild even when a matching release exists")
    args = parser.parse_args(argv)

    keys = args.maps or build.discover_maps()
    unknown = [k for k in keys if k not in build.discover_maps()]
    if unknown:
        raise SystemExit(f"unknown map key(s): {unknown}; try: python beamng_maps/build.py --list")

    if args.parts:
        print(f"== rejoining delivered parts from {args.parts}")
        try:
            join_parts.join(args.parts)
        except SystemExit as exc:
            print(f"   parts step: {exc}; maps without a verified ZIP will be built instead")

    for key in keys:
        ensure_release(key, force=args.force_rebuild)

    if args.no_deploy:
        print("dist ZIPs are ready; run: python beamng_maps/deploy_local.py --deploy")
        return 0
    print("== deploying into the BeamNG play profile")
    return deploy_local.main(["--deploy"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
