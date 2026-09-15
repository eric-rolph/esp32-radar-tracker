"""Build driver for the BeamNG maps pack (real terrain from public GIS data).

Usage (from the repository root):

    python beamng_maps/build.py <map_key> fetch    # public data -> <map>/data/ (cached)
    python beamng_maps/build.py <map_key> terrain  # data -> heightmap, layer map, stats
    python beamng_maps/build.py <map_key> level    # terrain -> mod/levels/<mod_id>/ tree
    python beamng_maps/build.py <map_key> dist     # mod/ -> dist ZIP + SHA-256 lock (re-zip only)
    python beamng_maps/build.py <map_key> ledger   # handoff -> the Build ledger table in DESIGN.md
    python beamng_maps/build.py <map_key> all
    python beamng_maps/build.py --all <stage>
    python beamng_maps/build.py --list

Each stage is deterministic given the cached data; ``dist`` is a re-zip of ``mod/``,
never a rebuild, exactly as in the giant props pack.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent
STAGES = ("fetch", "terrain", "level", "dist", "ledger")


def discover_maps() -> list[str]:
    return sorted(child.name for child in PACK_ROOT.iterdir() if child.is_dir() and (child / "spec.py").is_file())


def load_spec(map_key: str):
    spec_path = PACK_ROOT / map_key / "spec.py"
    if not spec_path.is_file():
        raise SystemExit(f"unknown map key: {map_key} (try --list)")
    loader = importlib.util.spec_from_file_location(f"beamng_maps_spec_{map_key}", spec_path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def run_stage(map_key: str, stage: str, *, force: bool = False) -> None:
    if str(PACK_ROOT) not in sys.path:
        sys.path.insert(0, str(PACK_ROOT))
    from maplib import pipeline

    spec = load_spec(map_key)
    example_root = PACK_ROOT / map_key
    print(f"== {map_key}: {stage}", flush=True)
    if stage == "fetch":
        pipeline.fetch(spec, example_root, force=force)
    elif stage == "terrain":
        pipeline.terrain(spec, example_root)
    elif stage == "level":
        pipeline.level(spec, example_root)
    elif stage == "dist":
        pipeline.dist(spec, example_root)
    elif stage == "ledger":
        pipeline.ledger(spec, example_root)
    else:
        raise SystemExit(f"unknown stage: {stage}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] == "--list":
        for key in discover_maps():
            print(key)
        return 0
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    keys = discover_maps() if argv[0] == "--all" else [argv[0]]
    stage = argv[1] if len(argv) > 1 else "all"
    stages = STAGES if stage == "all" else (stage,)
    for key in keys:
        for one in stages:
            run_stage(key, one, force=force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
