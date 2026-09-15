"""Stage implementations behind ``build.py``: fetch -> terrain -> level -> dist.

Each stage reads only what the previous one cached on disk, so a rebuild of any one
stage is reproducible on its own, and ``dist`` is a re-zip of ``mod/`` - never a rebuild.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np

from . import gis_sources
from . import heightmap as hm

HANDOFF_SCHEMA = "ericrolph-beamng-maps-handoff-v1"


def _log(message: str) -> None:
    print(message, flush=True)


def footprint_for(spec) -> gis_sources.Footprint:
    site = spec.SITE
    size_m = site["size_px"] * site["square_size_m"]
    return gis_sources.Footprint.from_center(site["center_lat"], site["center_lon"], site["epsg"], size_m)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def fetch(spec, example_root: Path, *, force: bool = False) -> dict:
    """Pull every public source the spec names into ``<map>/data/`` (cached, verified)."""

    data_root = example_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    fp = footprint_for(spec)
    _log(f"  footprint EPSG:{fp.epsg} W={fp.west:.0f} S={fp.south:.0f} size={fp.size_m:.0f} m")
    manifest: dict = {"footprint": fp.to_json(), "elevation": [], "imagery": None, "roads": None}
    for source in spec.SOURCES["elevation"]:
        kind = source["kind"]
        if kind == "usgs_3dep":
            paths = gis_sources.fetch_3dep_tiles(
                fp, data_root / "3dep", resolution=source.get("resolution", 1.0), force=force, log=_log
            )
            manifest["elevation"].append({"kind": kind, "files": [p.name for p in paths]})
        elif kind == "ot_tiles":
            paths = gis_sources.fetch_ot_tiles(
                source["prefix"], fp, data_root / "ot" / source["name"],
                pattern=source["pattern"], tile_m=source["tile_m"], force=force, log=_log,
            )
            manifest["elevation"].append({"kind": kind, "name": source["name"], "files": [p.name for p in paths]})
        elif kind == "ot_grid":
            path = gis_sources.fetch_ot_grid_window(
                source["prefix"], source["open_name"], fp,
                data_root / "ot" / f"{source['name']}_window.tif",
                cache_dir=data_root / "ot" / "_grid_cache", force=force, log=_log,
            )
            manifest["elevation"].append({"kind": kind, "name": source["name"], "files": [path.name]})
        else:
            raise ValueError(f"unknown elevation source kind: {kind}")
    imagery = spec.SOURCES.get("imagery")
    if imagery:
        paths = gis_sources.fetch_naip_tiles(
            fp, data_root / "naip", resolution=imagery.get("resolution", 1.0), force=force, log=_log
        )
        manifest["imagery"] = {"kind": imagery["kind"], "files": [p.name for p in paths]}
    roads = spec.SOURCES.get("roads")
    if roads:
        path = gis_sources.fetch_osm_roads(fp, data_root / "osm" / "roads.json", force=force, log=_log)
        manifest["roads"] = {"kind": roads["kind"], "files": [path.name]}
    (data_root / "fetch.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# terrain
# ---------------------------------------------------------------------------


def _source_resolution(path: Path) -> float:
    import rasterio

    with rasterio.open(path) as dataset:
        return float(dataset.res[0])


def terrain(spec, example_root: Path) -> dict:
    """Composite every elevation source onto the level grid; write dem/layer arrays + stats."""

    started = time.time()
    fp = footprint_for(spec)
    site = spec.SITE
    size = int(site["size_px"])
    res = float(site["square_size_m"])
    data_root = example_root / "data"
    out = data_root / "terrain"
    out.mkdir(parents=True, exist_ok=True)
    grid = hm.target_grid(fp, size, res)
    stats: dict = {"size_px": size, "square_size_m": res, "footprint": fp.to_json(), "sources": []}

    baseline_paths = sorted((data_root / "3dep").glob("3dep_*.tif"))
    if not baseline_paths:
        raise FileNotFoundError("run the fetch stage first: no 3DEP tiles cached")
    base_res = _source_resolution(baseline_paths[0])
    _log(f"  baseline: {len(baseline_paths)} 3DEP tiles @ {base_res:g} m -> {size}px @ {res:g} m")
    dem = hm.resample_sources(baseline_paths, grid, downsample=base_res < res)
    stats["sources"].append({"kind": "usgs_3dep", "tiles": len(baseline_paths), "valid_fraction": float(np.isfinite(dem).mean())})

    for source in spec.SOURCES["elevation"]:
        if source["kind"] == "usgs_3dep":
            continue
        if source["kind"] == "ot_tiles":
            paths = sorted((data_root / "ot" / source["name"]).glob("*.tif"))
        else:
            paths = [data_root / "ot" / f"{source['name']}_window.tif"]
        paths = [p for p in paths if p.is_file()]
        if not paths:
            raise FileNotFoundError(f"run the fetch stage first: no files for {source['name']}")
        src_res = _source_resolution(paths[0])
        _log(f"  overlay {source['name']}: {len(paths)} file(s) @ {src_res:g} m")
        overlay = hm.resample_sources(paths, grid, downsample=src_res < res)
        dem, composite_stats = hm.feathered_composite(dem, overlay, feather_px=max(8, int(24 / res)))
        stats["sources"].append({"kind": source["kind"], "name": source["name"], "files": len(paths), **composite_stats})
        _log(f"    covers {composite_stats['overlay_valid_fraction']:.1%} of the level, datum shift {composite_stats['datum_shift_m']:+.2f} m")

    dem, holes = hm.fill_holes(dem)
    stats["holes_filled"] = holes
    max_step = min(10.0, max(3.0, 8.0 * res))
    dem, spikes = hm.despike(dem, res, max_step_m=max_step)
    stats["spikes_clamped"] = spikes
    stats["despike_threshold_m"] = max_step
    sigma = float(spec.TERRAIN.get("smooth_sigma_px", 0.0))
    if sigma > 0:
        from scipy import ndimage

        dem = ndimage.gaussian_filter(dem, sigma=sigma).astype("float32")
    stats["smooth_sigma_px"] = sigma

    layer, fractions = hm.classify(dem, res, spec.TERRAIN)
    slope = hm.slope_degrees(dem, res)
    stats.update(
        {
            "min_elevation_m": float(dem.min()),
            "max_elevation_m": float(dem.max()),
            "mean_elevation_m": float(dem.mean()),
            "relief_m": float(dem.max() - dem.min()),
            "slope_mean_deg": float(slope.mean()),
            "slope_p95_deg": float(np.percentile(slope, 95)),
            "slope_over_30_fraction": float((slope > 30).mean()),
            "layer_fractions": fractions,
        }
    )
    np.save(out / "dem.npy", dem.astype("float32"))
    np.save(out / "layer.npy", layer.astype("uint8"))
    (out / "terrain.stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    _log(
        f"  elevation {stats['min_elevation_m']:.1f}..{stats['max_elevation_m']:.1f} m"
        f" (relief {stats['relief_m']:.0f} m), holes {holes}, spikes {spikes}, {time.time() - started:.0f} s"
    )
    return stats


# ---------------------------------------------------------------------------
# level
# ---------------------------------------------------------------------------


def level(spec, example_root: Path) -> dict:
    """Terrain arrays -> the complete mod/levels/<mod_id>/ tree + authoring evidence."""

    from . import level_builder

    started = time.time()
    fp = footprint_for(spec)
    data_root = example_root / "data"
    terrain_dir = data_root / "terrain"
    if not (terrain_dir / "dem.npy").is_file():
        raise FileNotFoundError("run the terrain stage first")
    dem = np.load(terrain_dir / "dem.npy")
    layer = np.load(terrain_dir / "layer.npy")
    terrain_stats = json.loads((terrain_dir / "terrain.stats.json").read_text())
    encoded = hm.encode(dem, layer)
    _log(f"  maxHeight {encoded.max_height_m:.0f} m over {encoded.min_elevation_m:.1f}..{encoded.max_elevation_m:.1f} m")
    report = level_builder.build_level(spec, example_root, fp, dem, layer, encoded, terrain_stats)
    level_root = Path(report["level_root"])
    _log(f"  roads: {report['roads']['roads']} decal roads, {report['roads']['length_m'] / 1000:.1f} km")

    # Authoring evidence: the handoff is the single source of truth the tests hash against.
    authoring = example_root / "authoring"
    authoring.mkdir(parents=True, exist_ok=True)
    shipped = {}
    for name in ("theTerrain.ter", "theTerrain.terrainheightmap.png", "theTerrain.terrain.json", "info.json", "art/terrains/main.materials.json"):
        path = level_root / name
        shipped[name] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "asset": {"id": spec.MOD_ID, "display_name": spec.DISPLAY_NAME, "zip": spec.ZIP_BASENAME},
        "site": dict(spec.SITE),
        "footprint": {**fp.to_json(), "bounds": list(fp.bounds), "wgs84_bbox_swne": list(fp.wgs84_bbox())},
        "sources": {
            "elevation": [
                {k: v for k, v in s.items() if k in ("kind", "name", "prefix", "resolution", "citation", "license")}
                for s in spec.SOURCES["elevation"]
            ],
            "imagery": "USGS/USDA NAIP orthoimagery via The National Map (public domain)",
            "roads": "OpenStreetMap contributors, ODbL 1.0",
        },
        "terrain": {
            "size_px": int(spec.SITE["size_px"]),
            "square_size_m": float(spec.SITE["square_size_m"]),
            "max_height_m": encoded.max_height_m,
            "min_elevation_m": encoded.min_elevation_m,
            "max_elevation_m": encoded.max_elevation_m,
            "terrain_block": report["terrain_block"],
            "materials": report["materials"],
            "stats": terrain_stats,
        },
        "roads": report["roads"],
        "spawns": report["spawns"],
        "shipped": shipped,
    }
    (authoring / f"{spec.MOD_ID}.handoff.json").write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copyfile(level_root / f"{spec.MOD_ID}_preview.jpg", authoring / f"{spec.MOD_ID}_thumbnail.jpg")
    _log(f"  level tree written in {time.time() - started:.0f} s")
    return handoff


# ---------------------------------------------------------------------------
# dist
# ---------------------------------------------------------------------------


def dist(spec, example_root: Path) -> dict:
    from . import packaging

    level_root = example_root / "mod" / "levels" / spec.MOD_ID
    for required in ("info.json", "theTerrain.ter", "main/items.level.json", "art/terrains/main.materials.json"):
        if not (level_root / required).is_file():
            raise FileNotFoundError(f"{spec.MOD_ID}: {required} missing - run the level stage before dist")
    return packaging.build_distribution(example_root, spec.MOD_ID, spec.ZIP_BASENAME)


# ---------------------------------------------------------------------------
# ledger: the DESIGN.md build ledger is generated from the handoff, never typed
# ---------------------------------------------------------------------------

LEDGER_HEADING = "## Build ledger"


def render_ledger(spec, example_root: Path) -> str:
    """Markdown for the DESIGN.md build ledger, from the handoff and the dist lock."""

    handoff = json.loads((example_root / "authoring" / f"{spec.MOD_ID}.handoff.json").read_text(encoding="utf-8"))
    terrain = handoff["terrain"]
    stats = terrain["stats"]
    rows = [
        ("Elevation range", f"{stats['min_elevation_m']:.1f} - {stats['max_elevation_m']:.1f} m (relief {stats['relief_m']:.0f} m)"),
        ("Terrain block", f"{terrain['size_px']} samples @ {terrain['square_size_m']:g} m, maxHeight {terrain['max_height_m']:.0f} m"),
    ]
    for source in stats["sources"]:
        if source["kind"] == "usgs_3dep":
            rows.append(("3DEP baseline coverage", f"{source['valid_fraction']:.1%} of the level before compositing"))
        else:
            rows.append((f"Lidar overlay `{source['name']}`", f"covers {source['overlay_valid_fraction']:.1%}, levelled by {source['datum_shift_m']:+.2f} m onto 3DEP"))
    rows += [
        ("Holes filled / spikes clamped", f"{stats['holes_filled']} / {stats['spikes_clamped']} (spike threshold {stats['despike_threshold_m']:g} m)"),
        ("Slope mean / p95 / over 30 deg", f"{stats['slope_mean_deg']:.1f} / {stats['slope_p95_deg']:.1f} deg / {stats['slope_over_30_fraction']:.1%}"),
        ("Layer split", ", ".join(f"{name} {fraction:.0%}" for name, fraction in sorted(stats["layer_fractions"].items(), key=lambda kv: -kv[1]))),
        ("Roads", f"{handoff['roads']['roads']} decal roads, {handoff['roads']['length_m'] / 1000:.1f} km ({', '.join(f'{k} {v}' for k, v in sorted(handoff['roads']['by_type'].items()))})"),
        ("Spawns", "; ".join(f"{s['objectname']} at ({s['level_xy'][0]:.0f}, {s['level_xy'][1]:.0f}), {s['z'] + terrain['min_elevation_m']:.0f} m" for s in handoff["spawns"])),
    ]
    lock_path = example_root / "dist" / f"{spec.MOD_ID}.lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        rows.append(("Distribution", f"`{lock['zip']}`, {lock['members']} members, {lock['size'] / 1e6:.1f} MB, sha256 `{lock['sha256'][:16]}...`, build serial {lock['build_serial']}"))
    lines = [LEDGER_HEADING, "", f"Generated by `build.py {example_root.name} ledger` from `authoring/{spec.MOD_ID}.handoff.json`; the handoff is authoritative.", "", "| Measured | Value |", "| --- | --- |"]
    lines += [f"| {key} | {value} |" for key, value in rows]
    return "\n".join(lines) + "\n"


def ledger(spec, example_root: Path) -> str:
    """Rewrite the ``## Build ledger`` section (through end of file) of DESIGN.md."""

    design_path = example_root / "DESIGN.md"
    text = design_path.read_text(encoding="utf-8")
    rendered = render_ledger(spec, example_root)
    index = text.find(LEDGER_HEADING)
    head = text[:index].rstrip("\n") + "\n\n" if index >= 0 else text.rstrip("\n") + "\n\n"
    design_path.write_text(head + rendered, encoding="utf-8", newline="\n")
    _log(f"  ledger rewritten in {design_path.name}")
    return rendered
