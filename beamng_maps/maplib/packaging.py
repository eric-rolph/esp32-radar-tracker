"""Deterministic distribution ZIP builder for the BeamNG maps pack.

Ported from the giant props pack's ``proplib/packaging.py`` and carrying the same
release policies, because every one of them was paid for:

- ``ZIP_STORED`` members only (level-9 DEFLATE is not byte-stable across zlib versions,
  which broke a cross-runtime SHA-256 lock once already),
- only approved BeamNG top-level folders inside the archive, no wrapper folder, no
  source or evidence files, no README,
- one stable ZIP filename per map; version lives in metadata, not the name,
- member timestamps that are MONOTONIC (a per-map build serial mapped to a date) and
  NEVER IN THE FUTURE. A future-dated member is newer than any cache the engine
  writes, so it re-cooks forever and the level renders on the IMPORTING TEXTURE
  placeholder (pachinko_tower build 34). ``future_dated_members`` is the hard gate.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

APPROVED_ROOTS = {
    "vehicles",
    "levels",
    "art",
    "assets",
    "lua",
    "scripts",
    "ui",
    "gameplay",
    "settings",
    "trackEditor",
    "vehicleGroups",
}
EXCLUDED_ROOTS = {"mod_info"}
SERIAL_BASE = datetime.date(2026, 8, 1)
CLAMP_MARGIN = datetime.timedelta(minutes=1)


def _serial_timestamp(serial: int, now: datetime.datetime | None = None) -> tuple[int, int, int, int, int, int]:
    """Monotonic member timestamp that is never in the future."""

    now = now or datetime.datetime.now()
    candidate = datetime.datetime.combine(SERIAL_BASE + datetime.timedelta(days=serial), datetime.time())
    ceiling = now - CLAMP_MARGIN
    stamp = min(candidate, ceiling)
    return (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)


def future_dated_members(archive: zipfile.ZipFile, now: datetime.datetime | None = None) -> list[str]:
    now = now or datetime.datetime.now()
    late = []
    for info in archive.infolist():
        if datetime.datetime(*info.date_time) > now:
            late.append(f"{info.filename} @ {datetime.datetime(*info.date_time).isoformat()}")
    return sorted(late)


def build_distribution(example_root: Path, mod_id: str, zip_basename: str) -> dict[str, Any]:
    mod_root = example_root / "mod"
    if not mod_root.is_dir():
        raise FileNotFoundError(f"mod tree is missing: {mod_root}")
    members: list[Path] = []
    for path in sorted(mod_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(mod_root)
        root = relative.parts[0]
        if root in EXCLUDED_ROOTS:
            continue
        if root not in APPROVED_ROOTS:
            raise ValueError(f"unapproved top-level folder in mod tree: {relative}")
        members.append(path)
    if not members:
        raise ValueError("mod tree contains no distributable files")

    dist_root = example_root / "dist"
    dist_root.mkdir(parents=True, exist_ok=True)
    zip_path = dist_root / zip_basename

    content_digest = hashlib.sha256()
    for path in members:
        content_digest.update(path.relative_to(mod_root).as_posix().encode())
        content_digest.update(path.read_bytes())
    content_sha = content_digest.hexdigest()
    serial_path = dist_root / f"{mod_id}.serial.json"
    serial_state = {"serial": 0, "content_sha": None}
    if serial_path.is_file():
        serial_state = json.loads(serial_path.read_text(encoding="utf-8"))
    if serial_state.get("content_sha") != content_sha:
        serial_state = {"serial": int(serial_state.get("serial", 0)) + 1, "content_sha": content_sha}
        serial_path.write_text(json.dumps(serial_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    timestamp = _serial_timestamp(int(serial_state["serial"]))

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in members:
            relative = path.relative_to(mod_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=timestamp)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())

    with zipfile.ZipFile(zip_path) as archive:
        late = future_dated_members(archive)
    if late:
        zip_path.unlink(missing_ok=True)
        listed = "\n".join(f"    {name}" for name in late[:6])
        raise ValueError(
            f"{mod_id}: {len(late)} ZIP member(s) are stamped in the FUTURE; BeamNG would re-cook them forever.\n{listed}"
        )

    payload = zip_path.read_bytes()
    lock = {
        "mod_id": mod_id,
        "zip": zip_basename,
        "members": len(members),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "build_serial": int(serial_state["serial"]),
        "timestamp_scheme": "monotonic-serial-days@2026-08-01-clamped-to-build-clock",
        "member_timestamp": datetime.datetime(*timestamp).isoformat(),
    }
    lock_path = dist_root / f"{mod_id}.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(lock, sort_keys=True))
    return lock
