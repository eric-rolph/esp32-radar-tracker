"""Rejoin delivered ZIP parts into ``<map>/dist/`` and write their release locks.

Whole level ZIPs are 80-90 MiB and the session's file delivery caps at 30 MiB, so a
build is handed over as ``<key>_ericrolph.zip.partN`` pieces plus ``SHA256SUMS.txt``.
This puts them back exactly where ``build.py <key> dist`` would have written them, so
``deploy_local.py`` can verify and install them like any other release.

Usage (from the repository root):

    python beamng_maps/join_parts.py <folder containing the .part files>

For every map whose parts are present it writes ``beamng_maps/<key>/dist/<key>_ericrolph.zip``
and ``beamng_maps/<key>/dist/ericrolph_<key>.lock.json``. A rejoined ZIP whose SHA-256 does not
match ``SHA256SUMS.txt`` is deleted, never installed.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent
PART_RE = re.compile(r"^(?P<key>[a-z_]+)_ericrolph\.zip\.part(?P<index>\d+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_sums(folder: Path) -> dict[str, str]:
    sums_path = folder / "SHA256SUMS.txt"
    if not sums_path.is_file():
        return {}
    sums = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def discover_parts(folder: Path) -> dict[str, list[Path]]:
    found: dict[str, list[tuple[int, Path]]] = {}
    for path in folder.iterdir():
        match = PART_RE.match(path.name)
        if match:
            found.setdefault(match.group("key"), []).append((int(match.group("index")), path))
    ordered = {}
    for key, entries in found.items():
        entries.sort()
        indices = [index for index, _ in entries]
        if indices != list(range(len(indices))):
            raise SystemExit(f"{key}: parts are not contiguous (have {indices})")
        ordered[key] = [path for _, path in entries]
    return ordered


def write_lock(zip_path: Path, mod_id: str, zip_basename: str) -> dict:
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise SystemExit(f"{zip_path.name}: ZIP integrity check failed")
        members = archive.infolist()
        if f"levels/{mod_id}/info.json" not in archive.namelist():
            raise SystemExit(f"{zip_path.name}: levels/{mod_id}/info.json is not in the archive")
        stamp = datetime.datetime(*members[0].date_time).isoformat() if members else None
    lock = {
        "mod_id": mod_id,
        "zip": zip_basename,
        "members": len(members),
        "size": zip_path.stat().st_size,
        "sha256": sha256_file(zip_path),
        "build_serial": 1,
        "timestamp_scheme": "monotonic-serial-days@2026-08-01-clamped-to-build-clock",
        "member_timestamp": stamp,
        "origin": "rejoined from delivered parts by join_parts.py",
    }
    lock_path = zip_path.parent / f"{mod_id}.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


def join(folder: Path) -> int:
    folder = folder.resolve()
    if not folder.is_dir():
        raise SystemExit(f"not a folder: {folder}")
    parts_by_key = discover_parts(folder)
    if not parts_by_key:
        raise SystemExit(f"no *_ericrolph.zip.partN files in {folder}")
    sums = read_sums(folder)
    failures = 0
    for key, parts in sorted(parts_by_key.items()):
        if not (PACK_ROOT / key / "spec.py").is_file():
            print(f"{key}: no such map in the pack, skipped")
            continue
        for part in parts:
            expected = sums.get(part.name)
            if expected and sha256_file(part) != expected:
                print(f"{key}: {part.name} does not match SHA256SUMS.txt (re-download it)")
                failures += 1
                break
        else:
            zip_basename = f"{key}_ericrolph.zip"
            dist = PACK_ROOT / key / "dist"
            dist.mkdir(parents=True, exist_ok=True)
            zip_path = dist / zip_basename
            with zip_path.open("wb") as sink:
                for part in parts:
                    sink.write(part.read_bytes())
            digest = sha256_file(zip_path)
            expected = sums.get(zip_basename)
            if expected and digest != expected:
                zip_path.unlink()
                print(f"{key}: rejoined ZIP hash {digest[:16]}... != expected {expected[:16]}..., deleted")
                failures += 1
                continue
            lock = write_lock(zip_path, f"ericrolph_{key}", zip_basename)
            note = "verified against SHA256SUMS.txt" if expected else "no SHA256SUMS.txt entry; integrity-checked only"
            print(f"{key}: {zip_basename} ({lock['size'] / 1e6:.1f} MB, {lock['members']} members) {note}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(join(Path(sys.argv[1])))
