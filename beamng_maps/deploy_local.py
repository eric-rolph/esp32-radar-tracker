"""Sync the locked map ZIPs into the local BeamNG play profile, verifiably.

Ported from the Giant Props pack's ``deploy_local.py`` and keeping its rules:

    python beamng_maps/deploy_local.py            # report status, exit 1 if anything is stale
    python beamng_maps/deploy_local.py --deploy   # copy what is stale, re-hash, report

1. A dist ZIP ships only if it byte-matches its own lock
   (``beamng_maps/<key>/dist/ericrolph_<key>.lock.json``). A ZIP that disagrees with its lock is a
   half-finished build (or a bad rejoin) and must be finished, not deployed.
2. Deployment is a byte copy to the profile's ``mods/`` ROOT under the stable ZIP filename,
   then a re-hash against the same lock. Nothing else is written: no backups parked under
   ``mods/`` (BeamNG mounts every zip below it recursively, so a stale copy shadows the
   release), no touching ``db.json``, ``repo/``, ``multiplayer/`` or any third-party zip.
3. The namespace shadow scan runs on CONTENT, never filename: every zip below ``mods/``
   is opened and checked for members under ``levels/<mod_id>/`` claimed by a file other
   than the map's own stable zip at the root.
4. ``--deploy`` refuses to run while a BeamNG process is alive: the engine rescans
   ``mods/`` on its own schedule and a swap under a running game is an unverifiable state.

The profile root is ``%LOCALAPPDATA%\\BeamNG\\BeamNG.drive\\current`` (the ``current``
version folder; on 0.3x installs check that ``mods/`` lives there and not under a
versioned folder such as ``0.39``). Override with ``BEAMNG_MAPS_PROFILE=<profile root>``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent


def profile_mods_root() -> Path:
    override = os.environ.get("BEAMNG_MAPS_PROFILE")
    if override:
        return Path(os.path.expandvars(override)) / "mods"
    local = os.environ.get("LOCALAPPDATA") or os.path.expandvars("%LOCALAPPDATA%")
    return Path(local) / "BeamNG" / "BeamNG.drive" / "current" / "mods"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Release:
    key: str
    mod_id: str
    display_name: str
    dist_zip: Path
    lock_sha256: str


def load_spec(key: str):
    loader = importlib.util.spec_from_file_location(f"beamng_maps_deploy_spec_{key}", PACK_ROOT / key / "spec.py")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def discover_releases() -> list[Release]:
    releases = []
    for child in sorted(PACK_ROOT.iterdir()):
        if not child.is_dir() or not (child / "spec.py").is_file():
            continue
        spec = load_spec(child.name)
        dist_zip = child / "dist" / spec.ZIP_BASENAME
        lock_path = child / "dist" / f"{spec.MOD_ID}.lock.json"
        if not dist_zip.is_file() or not lock_path.is_file():
            print(f"{child.name}: no dist zip + lock (build it, or rejoin delivered parts with join_parts.py)")
            continue
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        releases.append(Release(child.name, spec.MOD_ID, spec.DISPLAY_NAME, dist_zip, lock["sha256"]))
    return releases


def shadow_scan(mods_root: Path, releases: list[Release]) -> list[str]:
    """Content-based namespace ownership check across every zip below mods/."""

    owners = {release.mod_id: release.dist_zip.name for release in releases}
    findings = []
    for path in sorted(mods_root.rglob("*.zip")):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        except (zipfile.BadZipFile, OSError):
            continue
        for mod_id, stable in owners.items():
            if any(name.startswith(f"levels/{mod_id}/") for name in names):
                if path.parent != mods_root or path.name != stable:
                    findings.append(f"{path.relative_to(mods_root)} also carries levels/{mod_id}/ (owner: {stable} at the mods root)")
    return findings


def beamng_running() -> bool:
    if os.environ.get("BEAMNG_MAPS_ALLOW_RUNNING"):
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq BeamNG.drive.x64.exe"], capture_output=True, text=True, check=False).stdout
            return "BeamNG.drive.x64.exe" in out
        out = subprocess.run(["pgrep", "-fl", "BeamNG.drive"], capture_output=True, text=True, check=False).stdout
        return bool(out.strip())
    except OSError:
        return False


def main(argv: list[str]) -> int:
    deploy = "--deploy" in argv
    mods_root = profile_mods_root()
    print(f"profile mods root: {mods_root}")
    if not mods_root.is_dir():
        print("  not found: is BeamNG installed and has it been launched once? (or set BEAMNG_MAPS_PROFILE)")
        return 1
    releases = discover_releases()
    if not releases:
        print("nothing to deploy")
        return 1
    problems = 0
    stale: list[Release] = []
    for release in releases:
        local_sha = sha256_file(release.dist_zip)
        if local_sha != release.lock_sha256:
            print(f"{release.key}: dist zip does not match its lock ({local_sha[:12]} != {release.lock_sha256[:12]}); not deployable")
            problems += 1
            continue
        target = mods_root / release.dist_zip.name
        if target.is_file() and sha256_file(target) == release.lock_sha256:
            print(f"{release.key}: current ({release.display_name})")
        else:
            state = "stale" if target.is_file() else "missing"
            print(f"{release.key}: {state} -> {target.name}")
            stale.append(release)
    for finding in shadow_scan(mods_root, releases):
        print(f"CONFLICT: {finding}")
        problems += 1
    if not deploy:
        return 1 if (stale or problems) else 0
    if problems:
        print("refusing to deploy while conflicts or lock mismatches stand")
        return 1
    if beamng_running():
        print("refusing to deploy while BeamNG is running; close the game and re-run")
        return 1
    for release in stale:
        target = mods_root / release.dist_zip.name
        shutil.copyfile(release.dist_zip, target)
        if sha256_file(target) != release.lock_sha256:
            print(f"{release.key}: copy verification FAILED, removing {target.name}")
            target.unlink(missing_ok=True)
            return 1
        print(f"{release.key}: deployed {target.name} ({target.stat().st_size / 1e6:.1f} MB, sha256 verified)")
    print("done: launch BeamNG.drive -> Freeroam -> Select Level; the maps appear under their display names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
