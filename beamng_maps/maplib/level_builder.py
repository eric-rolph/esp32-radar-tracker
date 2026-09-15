"""Emit a complete BeamNG level tree from a spec plus the terrain stage's outputs.

Every file the game reads is generated here, never hand-edited (the giant props law):

    levels/<mod_id>/
      info.json                          level selector metadata + spawn points
      <mod_id>_preview.jpg               main thumbnail; spawn_<name>.jpg per spawn
      <mod_id>_minimap.png               orthoimagery minimap
      theTerrain.ter                     TerrainFile v9 (heights, layer map, materials)
      theTerrain.terrain.json            descriptive metadata the engine writes on save
      theTerrain.terrainheightmap.png    16-bit heightmap, north-up, for the Import Terrain tool
      main/items.level.json              MissionGroup
      main/MissionGroup/.../items.level.json   terrain, sky, level info, time, spawns, roads
      art/terrains/main.materials.json   TerrainMaterialTextureSet + one TerrainMaterial per layer
      art/terrains/*.png                 base set from orthoimagery + DEM, procedural detail/macro sets
      art/road/main.materials.json       the DecalRoad material and its textures

Formats follow documentation.beamng.com (level_formats/terrain, level_classes/*) and a
real shipped level's files, verified byte-level for the .ter material-name encoding
(u8 length prefix) and the version 9 payload (no v8 layerTextureMap block).
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import numpy as np

from . import heightmap as hm
from . import texture_kit

PID_NAMESPACE = uuid.UUID("6f4a4d3a-9b1e-4a83-9f7e-2c1c4b6b5e11")

GROUNDMODEL_BY_FAMILY = {
    "desert_floor": "DIRT_DUSTY",
    "gravel": "GRAVEL",
    "rock_strata": "ROCK",
    "scree": "GRAVEL",
    "dry_grass": "GRASS",
    "clay_pan": "DIRT",
    "shale": "DIRT_DUSTY",
    "volcanic_ash": "SAND",
    "snow": "SNOW",
    "alpine_tundra": "GRASS",
}

BASE_TEX_PX = 2048
DETAIL_TEX_PX = 512
MACRO_TEX_PX = 512
DETAIL_TILE_M = 2
MACRO_TILE_M = 60


def pid(mod_id: str, key: str) -> str:
    return str(uuid.uuid5(PID_NAMESPACE, f"{mod_id}:{key}"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_items(path: Path, objects: list[dict]) -> None:
    """items.level.json is line-delimited JSON: one complete object per line, no array."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(obj, separators=(",", ":"), sort_keys=False) for obj in objects]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def yaw_matrix(heading_deg: float) -> list[float]:
    """Row-major 3x3 rotation about Z for a compass heading (0 = north, clockwise).

    BeamNG vehicles spawn nose toward the spawn's -Y axis (the vehicle frame is +Y
    backward), so a heading of 0 (north, +Y) needs the marker turned 180 degrees.
    """

    yaw = math.radians(180.0 - heading_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    return [round(c, 9), round(s, 9), 0.0, round(-s, 9), round(c, 9), 0.0, 0.0, 0.0, 1.0]


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------


class Frame:
    """Level frame: metres east/north of the footprint centre; terrain samples north-up."""

    def __init__(self, fp, dem: np.ndarray, res: float, min_elevation: float):
        self.fp = fp
        self.dem = dem
        self.res = res
        self.min_elevation = min_elevation
        self.cx, self.cy = fp.center

    def to_level(self, easting: float, northing: float) -> tuple[float, float]:
        return (easting - self.cx, northing - self.cy)

    def lonlat_to_level(self, lon: float, lat: float) -> tuple[float, float]:
        from rasterio.warp import transform

        xs, ys = transform("EPSG:4326", f"EPSG:{self.fp.epsg}", [lon], [lat])
        return self.to_level(xs[0], ys[0])

    def inside(self, x: float, y: float, margin: float = 2.0) -> bool:
        half = self.fp.size_m / 2.0 - margin
        return -half <= x <= half and -half <= y <= half

    def height_at(self, x: float, y: float) -> float:
        """World Z (terrain position z = 0, heights relative to the lowest sample)."""

        size = self.dem.shape[0]
        col = (x + self.fp.size_m / 2.0) / self.res
        row = (self.fp.size_m / 2.0 - y) / self.res
        col = min(max(col, 0.0), size - 1.001)
        row = min(max(row, 0.0), size - 1.001)
        c0, r0 = int(col), int(row)
        fc, fr = col - c0, row - r0
        z = (
            self.dem[r0, c0] * (1 - fc) * (1 - fr)
            + self.dem[r0, c0 + 1] * fc * (1 - fr)
            + self.dem[r0 + 1, c0] * (1 - fc) * fr
            + self.dem[r0 + 1, c0 + 1] * fc * fr
        )
        return float(z - self.min_elevation)


# ---------------------------------------------------------------------------
# Roads
# ---------------------------------------------------------------------------


def _resample_polyline(points: list[tuple[float, float]], max_step: float) -> list[tuple[float, float]]:
    out = [points[0]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(math.ceil(length / max_step)))
        for i in range(1, steps + 1):
            t = i / steps
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def build_roads(spec, frame: Frame, osm_path: Path, *, max_step_m: float = 12.0) -> tuple[list[dict], dict]:
    """OSM highway ways -> DecalRoad objects clipped to the footprint and draped on the DEM."""

    payload = json.loads(osm_path.read_text(encoding="utf-8"))
    include = set(spec.ROADS["include"])
    widths = spec.ROADS["widths"]
    material = spec.ROADS["material"]["name"]
    roads: list[dict] = []
    stats: dict = {"ways_seen": 0, "roads": 0, "length_m": 0.0, "by_type": {}}
    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        highway = tags.get("highway")
        if highway not in include:
            continue
        stats["ways_seen"] += 1
        width = float(widths.get(highway, 4.0))
        points = [frame.lonlat_to_level(p["lon"], p["lat"]) for p in element.get("geometry", [])]
        # Split into runs that stay inside the footprint.
        runs: list[list[tuple[float, float]]] = [[]]
        for point in points:
            if frame.inside(*point):
                runs[-1].append(point)
            elif runs[-1]:
                runs.append([])
        for index, run in enumerate(r for r in runs if len(r) >= 2):
            dense = _resample_polyline(run, max_step_m)
            nodes = [[round(x, 3), round(y, 3), round(frame.height_at(x, y), 3), width] for x, y in dense]
            length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(nodes, nodes[1:]))
            if length < 15.0:
                continue
            name = f"road_{element['id']}_{index}"
            roads.append(
                {
                    "name": name,
                    "class": "DecalRoad",
                    "persistentId": pid(spec.MOD_ID, name),
                    "__parent": "roads",
                    "position": nodes[0][:3],
                    "improvedSpline": True,
                    "material": material,
                    "textureLength": 8,
                    "renderPriority": 10,
                    "startEndFade": [2, 2],
                    "drivability": 1,
                    "nodes": nodes,
                }
            )
            stats["roads"] += 1
            stats["length_m"] += length
            stats["by_type"][highway] = stats["by_type"].get(highway, 0) + 1
    stats["length_m"] = round(stats["length_m"], 1)
    return roads, stats


# ---------------------------------------------------------------------------
# Base textures from orthoimagery and the DEM
# ---------------------------------------------------------------------------


def naip_mosaic(naip_dir: Path, fp, out_px: int) -> np.ndarray:
    """Mosaic the cached NAIP tiles onto the footprint and resize to ``out_px`` (RGB8)."""

    from PIL import Image

    tiles = sorted(naip_dir.glob("naip_*.json"))
    if not tiles:
        raise FileNotFoundError(f"no NAIP tiles in {naip_dir}")
    meta = [json.loads(p.read_text()) for p in tiles]
    res = float(meta[0]["resolution_m"])
    full = int(round(fp.size_m / res))
    canvas = np.zeros((full, full, 3), dtype="uint8")
    for sidecar, info in zip(tiles, meta):
        image = Image.open(sidecar.with_suffix(".png")).convert("RGB")
        west, south, east, north = info["bounds"]
        col = int(round((west - fp.west) / res))
        row = int(round((fp.north - north) / res))
        array = np.asarray(image)
        h, w = array.shape[:2]
        canvas[row : row + h, col : col + w] = array[: full - row, : full - col]
    if full != out_px:
        canvas = np.asarray(Image.fromarray(canvas).resize((out_px, out_px), Image.LANCZOS))
    return canvas


def _resize_gray(array: np.ndarray, out_px: int) -> np.ndarray:
    from PIL import Image

    if array.shape[0] == out_px:
        return array
    image = Image.fromarray(array.astype("float32"), mode="F").resize((out_px, out_px), Image.BILINEAR)
    return np.asarray(image)


def build_base_set(dem: np.ndarray, res: float, fp, naip_dir: Path, out_dir: Path, prefix: str) -> dict[str, Path]:
    """t_base_{b,nm,r,h,ao}.png: the satellite-view base every terrain material shares."""

    out_dir.mkdir(parents=True, exist_ok=True)
    colour = naip_mosaic(naip_dir, fp, BASE_TEX_PX)
    small = _resize_gray(dem, BASE_TEX_PX)
    base_res = fp.size_m / BASE_TEX_PX
    normal = hm.normal_map(small, base_res, strength=1.0)
    ao = hm.ambient_occlusion(small, base_res, radius_px=12)
    lo, hi = float(small.min()), float(small.max())
    height = ((small - lo) / max(hi - lo, 1e-6) * 255.0).round().astype("uint8")
    luminance = colour.astype("float32").mean(axis=-1) / 255.0
    rough = np.clip(0.9 - 0.15 * luminance, 0.55, 0.95)
    paths = {}
    for suffix, array in (
        ("b", colour),
        ("nm", normal),
        ("r", (rough * 255).round().astype("uint8")),
        ("h", height),
        ("ao", (ao * 255).round().astype("uint8")),
    ):
        path = out_dir / f"{prefix}_{suffix}.png"
        hm.write_png8(path, array)
        paths[suffix] = path
    return paths


def build_previews(dem: np.ndarray, res: float, fp, naip_dir: Path, frame: Frame, spawns: list[dict], level_root: Path, mod_id: str) -> dict:
    """Preview JPGs: colour orthoimagery lit by a DEM hillshade, whole map and per spawn."""

    from PIL import Image

    colour = naip_mosaic(naip_dir, fp, 2048).astype("float32") / 255.0
    shade = hm.hillshade(_resize_gray(dem, 2048), fp.size_m / 2048, 315.0, 40.0)
    lit = np.clip(colour * (0.55 + 0.6 * shade[..., None]), 0.0, 1.0)
    image = Image.fromarray((lit * 255).round().astype("uint8"))
    previews = {}
    main = level_root / f"{mod_id}_preview.jpg"
    image.resize((1024, 1024), Image.LANCZOS).save(main, format="JPEG", quality=88)
    previews["main"] = main.name
    for spawn in spawns:
        x, y = spawn["level_xy"]
        px = (x + fp.size_m / 2) / fp.size_m * 2048
        py = (fp.size_m / 2 - y) / fp.size_m * 2048
        half = 256
        box = (int(px - half), int(py - half), int(px + half), int(py + half))
        crop = image.crop(box)
        path = level_root / f"{spawn['objectname']}.jpg"
        crop.resize((512, 512), Image.LANCZOS).save(path, format="JPEG", quality=85)
        previews[spawn["objectname"]] = path.name
    return previews


# ---------------------------------------------------------------------------
# The level
# ---------------------------------------------------------------------------


def terrain_material(mod_id: str, internal: str, family: str, groundmodel: str, level_url: str, base_prefix: str, macro_prefix: str, footprint_m: float) -> dict:
    """One TerrainMaterial in the v1.5 (base + macro + detail) layout of shipped levels.

    ``*TexSize`` on a material is WORLD metres the map tiles over (Torque's diffuseSize
    lineage): the shipped Utah2 level is 2048 m across and sets its base size to 2048
    while its texture set declares the same 2048 as PIXELS. The base map must cover the
    whole level exactly once, so it is the footprint here; detail and macro tile at
    their authored periods.
    """

    persistent = pid(mod_id, f"terrainmaterial:{internal}")
    tex = f"{level_url}/art/terrains"
    entry = {
        "name": f"{internal}-{persistent}",
        "internalName": internal,
        "class": "TerrainMaterial",
        "persistentId": persistent,
        "groundmodelName": groundmodel,
        "detailDistances": [0, 0, 50, 100],
        "detailDistAtten": [1, 1],
        "macroDistances": [0, 10, 100, 3000],
        "macroDistAtten": [0, 1],
        "baseColorDetailStrength": [0.35, 0.35],
        "normalDetailStrength": [0.7, 0.3],
        "roughnessDetailStrength": [0.3, 0.3],
        "aoDetailStrength": [1, 1],
        "baseColorMacroStrength": [0.1, 0.25],
        "normalMacroStrength": [0.4, 0.5],
        "roughnessMacroStrength": [0.15, 0.5],
    }
    for channel, suffix in (("baseColor", "b"), ("normal", "nm"), ("roughness", "r"), ("height", "h"), ("ao", "ao")):
        entry[f"{channel}BaseTex"] = f"{tex}/{base_prefix}_{suffix}.png"
        entry[f"{channel}BaseTexSize"] = int(footprint_m)
        entry[f"{channel}DetailTex"] = f"{tex}/t_{internal}_{suffix}.png"
        entry[f"{channel}DetailTexSize"] = DETAIL_TILE_M
        entry[f"{channel}MacroTex"] = f"{tex}/{macro_prefix}_{suffix}.png"
        entry[f"{channel}MacroTexSize"] = MACRO_TILE_M
    return entry


def build_level(spec, example_root: Path, fp, dem: np.ndarray, layer: np.ndarray, encoded: hm.Encoded, terrain_stats: dict) -> dict:
    mod_id = spec.MOD_ID
    site = spec.SITE
    res = float(site["square_size_m"])
    size = int(site["size_px"])
    level_root = example_root / "mod" / "levels" / mod_id
    if level_root.exists():
        import shutil

        shutil.rmtree(level_root)
    level_root.mkdir(parents=True)
    level_url = f"/levels/{mod_id}"
    data_root = example_root / "data"
    frame = Frame(fp, dem, res, encoded.min_elevation_m)
    materials = list(spec.TERRAIN["materials"])
    report: dict = {"files": {}}

    # --- terrain binary + metadata + heightmap PNG ---------------------------------
    hm.write_ter(level_root / "theTerrain.ter", encoded.heights_u16_south_up, encoded.layer_u8_south_up, materials)
    hm.write_png16(level_root / "theTerrain.terrainheightmap.png", encoded.heights_u16_north_up)
    write_json(
        level_root / "theTerrain.terrain.json",
        {
            "version": 9,
            "datafile": f"{level_url}/theTerrain.ter",
            "heightmapImage": f"{level_url}/theTerrain.terrainheightmap.png",
            "size": size,
            "binaryFormat": "version(char), size(unsigned int), heightMap(heightMapSize * heightMapItemSize), layerMap(layerMapSize * layerMapItemSize), materialNames",
            "heightMapSize": size * size,
            "heightMapItemSize": 2,
            "layerMapSize": size * size,
            "layerMapItemSize": 1,
            "materials": materials,
        },
    )

    # --- textures ----------------------------------------------------------------
    terrains_dir = level_root / "art" / "terrains"
    base_prefix = "t_base"
    macro_prefix = "t_macro"
    build_base_set(dem, res, fp, data_root / "naip", terrains_dir, base_prefix)
    texture_kit.build_set(terrains_dir, macro_prefix, "macro_clumpy", seed=7, size=MACRO_TEX_PX, base_rgb=[0.5, 0.5, 0.5])
    material_entries = {}
    texture_set_name = f"{mod_id}_TerrainTextureSet"
    material_entries[texture_set_name] = {
        "name": texture_set_name,
        "class": "TerrainMaterialTextureSet",
        "persistentId": pid(mod_id, "texture_set"),
        "baseTexSize": [BASE_TEX_PX, BASE_TEX_PX],
        "detailTexSize": [DETAIL_TEX_PX, DETAIL_TEX_PX],
        "macroTexSize": [MACRO_TEX_PX, MACRO_TEX_PX],
    }
    for internal in materials:
        palette = spec.PALETTE[internal]
        texture_kit.build_set(terrains_dir, f"t_{internal}", palette["family"], seed=int(palette["seed"]), size=DETAIL_TEX_PX, base_rgb=palette["base"])
        groundmodel = palette.get("groundmodel") or GROUNDMODEL_BY_FAMILY[palette["family"]]
        entry = terrain_material(mod_id, internal, palette["family"], groundmodel, level_url, base_prefix, macro_prefix, fp.size_m)
        material_entries[entry["name"]] = entry
    write_json(terrains_dir / "main.materials.json", material_entries)

    # --- road material -----------------------------------------------------------
    road_dir = level_root / "art" / "road"
    road_spec = spec.ROADS["material"]
    road_name = road_spec["name"]
    texture_kit.build_set(road_dir, road_name, road_spec["family"], seed=int(road_spec["seed"]), size=512, base_rgb=road_spec["base"])
    _feather_road_alpha(road_dir / f"{road_name}_b.png")
    write_json(
        road_dir / "main.materials.json",
        {
            road_name: {
                "name": road_name,
                "class": "Material",
                "mapTo": road_name,
                "persistentId": pid(mod_id, f"material:{road_name}"),
                "Stages": [
                    {
                        "baseColorMap": f"{level_url}/art/road/{road_name}_b.png",
                        "normalMap": f"{level_url}/art/road/{road_name}_nm.png",
                        "roughnessMap": f"{level_url}/art/road/{road_name}_r.png",
                        "useAnisotropic": True,
                    },
                    {},
                    {},
                    {},
                ],
                "annotation": "DRIVABLE_ROAD",
                "materialTag0": "RoadAndPath",
                "materialTag1": "beamng",
                "translucent": True,
                "translucentBlendOp": "LerpAlpha",
                "translucentZWrite": False,
                "version": 1.5,
            }
        },
    )

    # --- spawns ------------------------------------------------------------------
    spawns = []
    for entry in spec.SPAWNS:
        x, y = frame.lonlat_to_level(entry["lon"], entry["lat"])
        if not frame.inside(x, y, margin=20.0):
            raise ValueError(f"{mod_id}: spawn {entry['name']} lies outside the footprint")
        spawns.append(
            {
                "objectname": f"spawn_{entry['name']}",
                "label": entry["name"].replace("_", " ").title(),
                "level_xy": (round(x, 2), round(y, 2)),
                "z": round(frame.height_at(x, y) + 0.5, 2),
                "heading_deg": float(entry.get("heading_deg", 0.0)),
                "default": bool(entry.get("default", False)),
                "lat": entry["lat"],
                "lon": entry["lon"],
            }
        )
    default_spawn = next((s for s in spawns if s["default"]), spawns[0])

    # --- roads -------------------------------------------------------------------
    roads, road_stats = build_roads(spec, frame, data_root / "osm" / "roads.json")

    # --- previews + minimap --------------------------------------------------------
    previews = build_previews(dem, res, fp, data_root / "naip", frame, spawns, level_root, mod_id)
    from PIL import Image

    Image.fromarray(naip_mosaic(data_root / "naip", fp, 1024)).save(level_root / f"{mod_id}_minimap.png", format="PNG", compress_level=6)

    # --- scene tree ---------------------------------------------------------------
    main = level_root / "main"
    footprint = float(fp.size_m)
    write_items(main / "items.level.json", [{"name": "MissionGroup", "class": "SimGroup", "enabled": "1", "persistentId": pid(mod_id, "MissionGroup")}])
    write_items(
        main / "MissionGroup" / "items.level.json",
        [
            {"name": "Level_objects", "class": "SimGroup", "persistentId": pid(mod_id, "Level_objects"), "__parent": "MissionGroup"},
            {"name": "PlayerDropPoints", "class": "SimGroup", "persistentId": pid(mod_id, "PlayerDropPoints"), "__parent": "MissionGroup"},
            {"name": "roads", "class": "SimGroup", "persistentId": pid(mod_id, "roads"), "__parent": "MissionGroup"},
        ],
    )
    write_items(
        main / "MissionGroup" / "Level_objects" / "items.level.json",
        [
            {"name": "terrain", "class": "SimGroup", "persistentId": pid(mod_id, "terrain"), "__parent": "Level_objects"},
            {"name": "Sky", "class": "SimGroup", "persistentId": pid(mod_id, "Sky"), "__parent": "Level_objects"},
            {"name": "level_info", "class": "SimGroup", "persistentId": pid(mod_id, "level_info"), "__parent": "Level_objects"},
            {"name": "time", "class": "SimGroup", "persistentId": pid(mod_id, "time"), "__parent": "Level_objects"},
        ],
    )
    write_items(
        main / "MissionGroup" / "Level_objects" / "terrain" / "items.level.json",
        [
            {
                "name": "theTerrain",
                "class": "TerrainBlock",
                "persistentId": pid(mod_id, "theTerrain"),
                "__parent": "terrain",
                "position": [-footprint / 2.0, -footprint / 2.0, 0],
                "rotationMatrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "terrainFile": f"{level_url}/theTerrain.ter",
                "materialTextureSet": texture_set_name,
                "minimapImage": f"levels/{mod_id}/{mod_id}_minimap.png",
                "squareSize": res,
                "maxHeight": encoded.max_height_m,
                "baseTexSize": BASE_TEX_PX,
                "lightMapSize": 1024,
                "screenError": 16,
                "castShadows": True,
            }
        ],
    )
    write_items(
        main / "MissionGroup" / "Level_objects" / "Sky" / "items.level.json",
        [
            {
                "name": "sunsky",
                "class": "ScatterSky",
                "persistentId": pid(mod_id, "sunsky"),
                "__parent": "Sky",
                "position": [0, 0, 0],
                "rotationMatrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "scale": [1, 1, 1],
                "ambientScale": [1, 0.894117653, 0.78039217, 1],
                "ambientScaleGradientFile": "art/sky_gradients/default/gradient_ambient.png",
                "brightness": 0.9,
                "colorize": [0.215686277, 0.349019617, 0.603921592, 1],
                "colorizeGradientFile": "art/sky_gradients/default/gradient_colorize.png",
                "exposure": 1.4,
                "fadeStartDistance": 1000,
                "flareScale": 10,
                "flareType": "BNG_Sunflare_2",
                "fogScale": [0.396078438, 0.666666687, 1, 1],
                "fogScaleGradientFile": "art/sky_gradients/default/gradient_fog.png",
                "logWeight": 0.98,
                "mieScattering": 0.000401154364,
                "moonLightColor": [0.0980392024, 0.0980392024, 0.0980392024, 1],
                "moonMat": "Moon_Glow_Mat",
                "moonScale": 0.03,
                "nightColor": [1, 0.894117653, 0.78039217, 1],
                "nightCubemap": "nightCubemap",
                "nightFogColor": [0.396078438, 0.666666687, 1, 1],
                "nightFogGradientFile": "art/sky_gradients/default/gradient_fog.png",
                "nightGradientFile": "art/sky_gradients/default/gradient_ambient.png",
                "occlusionScale": 0.3,
                "shadowDistance": 1600,
                "shadowSoftness": 0.2,
                "skyBrightness": 42,
                "sunScale": [0.996078432, 0.831372559, 0.729411781, 1],
                "sunScaleGradientFile": "art/sky_gradients/default/gradient_sunscale.png",
                "texSize": 1024,
                "useNightCubemap": True,
            }
        ],
    )
    write_items(
        main / "MissionGroup" / "Level_objects" / "level_info" / "items.level.json",
        [
            {
                "name": "theLevelInfo",
                "class": "LevelInfo",
                "persistentId": pid(mod_id, "theLevelInfo"),
                "__parent": "level_info",
                "nearClip": 0.1,
                "visibleDistance": 9000,
                "decalBias": 0.0005,
                "fogDensity": 0.00015,
                "fogAtmosphereHeight": 1500,
                "canvasClearColor": [0, 0, 0, 255],
                "gravity": -9.80665,
                "levelName": spec.DISPLAY_NAME,
                "desc0": spec.FEATURES,
                "fogColor": [0.574180365, 0.77074331, 1, 1],
                "fogDensityOffset": 1,
                "temperatureCurveC": [0, 12, 0.25, 24, 0.5, 30, 0.75, 22, 1, 12],
                "ambientLightBlendPhase": 1,
                "advancedLightmapSupport": False,
                "globalEnviromentMap": "DefaultSkyCubemap",
                "soundAmbience": "AudioAmbienceDefault",
                "soundDistanceModel": "Logarithmic",
                "bigMapLevelBorderVisible": True,
            }
        ],
    )
    sky = spec.SKY
    write_items(
        main / "MissionGroup" / "Level_objects" / "time" / "items.level.json",
        [
            {
                "name": "tod",
                "class": "TimeOfDay",
                "persistentId": pid(mod_id, "tod"),
                "__parent": "time",
                "position": [0, 0, 0],
                "rotationMatrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "scale": [1, 1, 1],
                "axisTilt": 23.44,
                "dayLength": 1800,
                "startTime": float(sky["time"]),
                "time": float(sky["time"]),
                "play": False,
                "latitude": float(site["center_lat"]),
                "longitude": float(site["center_lon"]),
                "year": int(sky.get("year", 2026)),
                "month": int(sky.get("month", 6)),
                "day": int(sky.get("day", 20)),
                "utcOffset": str(sky.get("utc_offset", "-7")),
                "celestialProfile": "earth",
            }
        ],
    )
    spawn_objects = []
    for spawn in spawns:
        x, y = spawn["level_xy"]
        spawn_objects.append(
            {
                "name": spawn["objectname"],
                "class": "SpawnSphere",
                "persistentId": pid(mod_id, spawn["objectname"]),
                "__parent": "PlayerDropPoints",
                "position": [x, y, spawn["z"]],
                "rotationMatrix": yaw_matrix(spawn["heading_deg"]),
                "scale": [1, 1, 1],
                "dataBlock": "SpawnSphereMarker",
                "radius": 5,
                "autoplaceOnSpawn": "0",
                "homingCount": "0",
                "indoorWeight": "1",
                "outdoorWeight": "1",
                "lockCount": "0",
                "sphereWeight": "1",
            }
        )
    write_items(main / "MissionGroup" / "PlayerDropPoints" / "items.level.json", spawn_objects)
    write_items(main / "MissionGroup" / "roads" / "items.level.json", roads)

    # --- info.json ---------------------------------------------------------------
    attribution = " ".join(
        f"{s['citation']}." for s in spec.SOURCES["elevation"] if s.get("citation")
    )
    description = (
        f"{spec.DESCRIPTION} Elevation: USGS 3DEP (public domain){'; ' + attribution if attribution else ''}"
        " Imagery: USGS/USDA NAIP (public domain). Roads: (c) OpenStreetMap contributors, ODbL."
    )
    write_json(
        level_root / "info.json",
        {
            "title": spec.DISPLAY_NAME,
            "description": description,
            "authors": spec.AUTHOR,
            "country": "levels.common.country.usa",
            "region": "northAmerica",
            "biome": spec.BIOME,
            "features": spec.FEATURES,
            "suitablefor": spec.SUITABLE_FOR,
            "roads": spec.ROADS_TEXT,
            "size": [int(footprint), int(footprint)],
            "supportsTraffic": False,
            "supportsTimeOfDay": True,
            "defaultDate": {"year": int(sky.get("year", 2026)), "month": int(sky.get("month", 6)), "day": int(sky.get("day", 20))},
            "defaultSpawnPointName": default_spawn["objectname"],
            "previews": [previews["main"]],
            "spawnPoints": [
                {
                    "translationId": spawn["label"],
                    "description": f"{spawn['label']} ({spawn['lat']:.4f}, {spawn['lon']:.4f})",
                    "objectname": spawn["objectname"],
                    "preview": previews[spawn["objectname"]],
                }
                for spawn in spawns
            ],
        },
    )
    report.update(
        {
            "level_root": str(level_root),
            "spawns": spawns,
            "roads": road_stats,
            "materials": materials,
            "texture_set": texture_set_name,
            "terrain_block": {"position": [-footprint / 2.0, -footprint / 2.0, 0], "squareSize": res, "maxHeight": encoded.max_height_m, "size": size},
        }
    )
    return report


def _feather_road_alpha(colour_path: Path, edge_fraction: float = 0.18) -> None:
    """Give the decal-road colour map a soft alpha edge across its width (U axis)."""

    from PIL import Image

    image = Image.open(colour_path).convert("RGBA")
    array = np.asarray(image).copy()
    width = array.shape[1]
    u = (np.arange(width) + 0.5) / width
    edge = np.clip(np.minimum(u, 1.0 - u) / edge_fraction, 0.0, 1.0)
    alpha = (edge * edge * (3 - 2 * edge) * 255).round().astype("uint8")
    array[..., 3] = alpha[None, :]
    Image.fromarray(array, mode="RGBA").save(colour_path, format="PNG", compress_level=6)
