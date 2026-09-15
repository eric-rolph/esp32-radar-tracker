"""Static structural gates for the BeamNG maps pack.

Every spec is validated on its own; the artefact gates (handoff hashes against the
generated level tree, the .ter binary, the scene files, the ZIP lock) run when the map
has been built and skip with a reason otherwise, because ``mod/`` and ``dist/`` are build
output the repository deliberately does not track.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

PACK_ROOT = Path(__file__).resolve().parents[1] / "beamng_maps"
HANDOFF_SCHEMA = "ericrolph-beamng-maps-handoff-v1"
APPROVED_ROOTS = {"vehicles", "levels", "art", "assets", "lua", "scripts", "ui", "gameplay", "settings", "trackEditor", "vehicleGroups"}
MAP_KEYS = sorted(child.name for child in PACK_ROOT.iterdir() if child.is_dir() and (child / "spec.py").is_file())


def load_spec(map_key: str):
    spec_path = PACK_ROOT / map_key / "spec.py"
    loader = importlib.util.spec_from_file_location(f"beamng_maps_test_spec_{map_key}", spec_path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def load_maplib():
    if str(PACK_ROOT) not in sys.path:
        sys.path.insert(0, str(PACK_ROOT))
    from maplib import gis_sources, heightmap, level_builder, packaging, pipeline, texture_kit

    return gis_sources, heightmap, level_builder, packaging, pipeline, texture_kit


def level_root(map_key: str) -> Path:
    spec = load_spec(map_key)
    return PACK_ROOT / map_key / "mod" / "levels" / spec.MOD_ID


def require_built(map_key: str) -> Path:
    root = level_root(map_key)
    if not (root / "info.json").is_file():
        pytest.skip(f"{map_key}: level not built (python beamng_maps/build.py {map_key} all)")
    return root


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_items(path: Path) -> list[dict]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    objects = [json.loads(line) for line in lines]
    assert path.read_text(encoding="utf-8").lstrip()[0] == "{", f"{path}: items.level.json must not be a JSON array"
    return objects


def all_items(main: Path) -> list[tuple[Path, dict]]:
    return [(path, obj) for path in sorted(main.rglob("items.level.json")) for obj in read_items(path)]


# ---------------------------------------------------------------------------
# Spec gates
# ---------------------------------------------------------------------------


def test_pack_has_all_maps() -> None:
    # A literal, bumped by one for the map you add, so a spec silently dropping out of
    # discovery is a red suite and not a smaller green one.
    assert len(MAP_KEYS) == 6, MAP_KEYS


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_spec_identity(map_key: str) -> None:
    spec = load_spec(map_key)
    assert spec.MOD_ID == f"ericrolph_{map_key}"
    assert spec.ZIP_BASENAME == f"{map_key}_ericrolph.zip"
    assert spec.AUTHOR == "ericrolph"
    for field in ("DISPLAY_NAME", "DESCRIPTION", "BIOME", "FEATURES", "SUITABLE_FOR", "ROADS_TEXT"):
        assert isinstance(getattr(spec, field), str) and getattr(spec, field).strip(), field


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_spec_footprint_is_a_beamng_terrain(map_key: str) -> None:
    site = load_spec(map_key).SITE
    size = site["size_px"]
    assert size & (size - 1) == 0 and 1024 <= size <= 8192, "heightmap edge must be a power of two"
    assert site["square_size_m"] in (0.5, 1.0, 1.5, 2.0)
    assert size * site["square_size_m"] <= 8192
    assert 32601 <= site["epsg"] <= 32660, "sites are placed in WGS 84 UTM north zones"
    assert -90 < site["center_lat"] < 90 and -180 < site["center_lon"] < 180


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_spec_materials_and_rules_agree(map_key: str) -> None:
    spec = load_spec(map_key)
    materials = spec.TERRAIN["materials"]
    assert len(materials) == len(set(materials)) and 1 <= len(materials) <= 254
    assert spec.TERRAIN["classify"]["default"] in materials
    for rule in spec.TERRAIN["classify"]["rules"]:
        assert rule["material"] in materials, rule
        assert set(rule) - {"material"} <= {"min_slope", "max_slope", "min_elevation_frac", "max_elevation_frac"}
    _, _, level_builder, _, _, texture_kit = load_maplib()
    for name in materials:
        palette = spec.PALETTE[name]
        assert palette["family"] in texture_kit.FAMILIES, palette["family"]
        assert palette["family"] in level_builder.GROUNDMODEL_BY_FAMILY or palette.get("groundmodel")
        assert len(palette["base"]) == 3 and all(0.0 <= c <= 1.0 for c in palette["base"])
    road = spec.ROADS["material"]
    assert road["family"] in texture_kit.FAMILIES
    assert set(spec.ROADS["include"]) <= set(spec.ROADS["widths"]), "every included highway type needs a width"


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_spec_spawns_lie_inside_the_footprint(map_key: str) -> None:
    spec = load_spec(map_key)
    gis_sources, _, _, _, pipeline, _ = load_maplib()
    fp = pipeline.footprint_for(spec)
    from rasterio.warp import transform

    defaults = 0
    names = set()
    for spawn in spec.SPAWNS:
        xs, ys = transform("EPSG:4326", f"EPSG:{fp.epsg}", [spawn["lon"]], [spawn["lat"]])
        assert fp.west + 20 <= xs[0] <= fp.east - 20 and fp.south + 20 <= ys[0] <= fp.north - 20, spawn["name"]
        defaults += bool(spawn.get("default"))
        names.add(spawn["name"])
    assert defaults == 1, "exactly one default spawn"
    assert len(names) == len(spec.SPAWNS)
    assert 0.0 <= spec.SKY["time"] < 1.0


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_spec_sources_carry_citations(map_key: str) -> None:
    spec = load_spec(map_key)
    kinds = [s["kind"] for s in spec.SOURCES["elevation"]]
    assert kinds[0] == "usgs_3dep", "3DEP is the baseline every other source is levelled onto"
    for source in spec.SOURCES["elevation"][1:]:
        assert source.get("citation") and source.get("license"), source["name"]
        if source["kind"] == "ot_tiles":
            assert "(\\d+)" in source["pattern"] and source["tile_m"] > 0


# ---------------------------------------------------------------------------
# Toolkit gates (no data needed)
# ---------------------------------------------------------------------------


def test_ter_roundtrip(tmp_path: Path) -> None:
    _, hm, _, _, _, _ = load_maplib()
    dem = (np.random.default_rng(3).random((64, 64)) * 120.0 + 1500.0).astype("float32")
    layer = (np.arange(64 * 64).reshape(64, 64) % 3).astype("uint8")
    encoded = hm.encode(dem, layer)
    path = tmp_path / "t.ter"
    hm.write_ter(path, encoded.heights_u16_south_up, encoded.layer_u8_south_up, ["a", "bb", "ccc"])
    raw = path.read_bytes()
    version, size = struct.unpack("<BI", raw[:5])
    assert version == 9 and size == 64
    heights = np.frombuffer(raw[5 : 5 + 2 * 64 * 64], dtype="<u2").reshape(64, 64)
    layers = np.frombuffer(raw[5 + 2 * 64 * 64 : 5 + 3 * 64 * 64], dtype="u1").reshape(64, 64)
    assert raw[5 + 3 * 64 * 64 :] == b"\x03\x00\x00\x00" + b"\x01a" + b"\x02bb" + b"\x03ccc"
    assert np.array_equal(heights, encoded.heights_u16_north_up[::-1])
    assert np.array_equal(layers, layer[::-1])
    decoded = heights.astype("float64") * encoded.max_height_m / 65536.0 + encoded.min_elevation_m
    assert np.abs(decoded[::-1] - dem).max() < encoded.max_height_m / 65536.0 + 1e-3
    assert encoded.max_height_m >= float(dem.max() - dem.min())


def test_texture_kit_is_deterministic(tmp_path: Path) -> None:
    _, _, _, _, _, texture_kit = load_maplib()
    a = texture_kit.build_set(tmp_path / "a", "x", "gravel", seed=42, size=64, base_rgb=[0.5, 0.4, 0.3])
    b = texture_kit.build_set(tmp_path / "b", "x", "gravel", seed=42, size=64, base_rgb=[0.5, 0.4, 0.3])
    for suffix in ("b", "nm", "r", "h", "ao"):
        assert a[suffix].read_bytes() == b[suffix].read_bytes(), suffix
    c = texture_kit.build_set(tmp_path / "c", "x", "gravel", seed=43, size=64, base_rgb=[0.5, 0.4, 0.3])
    assert a["b"].read_bytes() != c["b"].read_bytes(), "a different seed must change the map"


def test_texture_tiles_wrap() -> None:
    _, _, _, _, _, texture_kit = load_maplib()
    rng = np.random.default_rng(1)
    noise = texture_kit.fbm(128, 4, 3, rng)
    # Periodic noise: the step across the wrap edge is no larger than interior steps.
    interior = np.abs(np.diff(noise, axis=1)).max()
    wrap = np.abs(noise[:, 0] - noise[:, -1]).max()
    assert wrap <= interior * 1.5


def test_yaw_matrix_convention() -> None:
    _, _, level_builder, _, _, _ = load_maplib()
    north = level_builder.yaw_matrix(0.0)
    south = level_builder.yaw_matrix(180.0)
    assert south == [1.0, 0.0, 0.0, -0.0, 1.0, 0.0, 0.0, 0.0, 1.0] or south[0] == 1.0
    assert north[0] == -1.0 and north[4] == -1.0


def test_packaging_refuses_unapproved_roots(tmp_path: Path) -> None:
    _, _, _, packaging, _, _ = load_maplib()
    (tmp_path / "mod" / "README").parent.mkdir(parents=True)
    (tmp_path / "mod" / "README").write_text("no")
    with pytest.raises(ValueError):
        packaging.build_distribution(tmp_path, "x", "x.zip")


# ---------------------------------------------------------------------------
# Artefact gates (built maps only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_handoff_hashes_match_shipped_files(map_key: str) -> None:
    root = require_built(map_key)
    spec = load_spec(map_key)
    handoff = json.loads((PACK_ROOT / map_key / "authoring" / f"{spec.MOD_ID}.handoff.json").read_text())
    assert handoff["schema"] == HANDOFF_SCHEMA
    assert handoff["asset"]["id"] == spec.MOD_ID
    for name, record in handoff["shipped"].items():
        path = root / name
        assert path.stat().st_size == record["size"], name
        assert sha256_file(path) == record["sha256"], name
    assert (PACK_ROOT / map_key / "authoring" / f"{spec.MOD_ID}_thumbnail.jpg").is_file()


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_ter_binary_is_well_formed(map_key: str) -> None:
    root = require_built(map_key)
    spec = load_spec(map_key)
    size = spec.SITE["size_px"]
    raw = (root / "theTerrain.ter").read_bytes()
    version, stored_size = struct.unpack("<BI", raw[:5])
    assert version == 9 and stored_size == size
    materials = json.loads((root / "theTerrain.terrain.json").read_text())["materials"]
    assert materials == spec.TERRAIN["materials"]
    names = b"".join(struct.pack("<B", len(m)) + m.encode() for m in materials)
    assert len(raw) == 5 + 3 * size * size + 4 + len(names)
    assert raw[5 + 3 * size * size :] == struct.pack("<I", len(materials)) + names
    heights = np.frombuffer(raw[5 : 5 + 2 * size * size], dtype="<u2")
    layers = np.frombuffer(raw[5 + 2 * size * size : 5 + 3 * size * size], dtype="u1")
    assert heights.min() == 0, "heights are relative to the lowest sample"
    assert heights.max() > 1000, "the 16-bit ladder must actually be used"
    valid = (layers < len(materials)) | (layers == 255)
    assert valid.all()
    assert (layers == 255).mean() == 0.0, "no holes are authored in these maps"


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_heightmap_png_is_16_bit_and_row_consistent(map_key: str) -> None:
    from PIL import Image

    root = require_built(map_key)
    spec = load_spec(map_key)
    size = spec.SITE["size_px"]
    image = Image.open(root / "theTerrain.terrainheightmap.png")
    assert image.mode in ("I;16", "I") and image.size == (size, size)
    png = np.asarray(image).astype("uint16")
    raw = (root / "theTerrain.ter").read_bytes()
    ter = np.frombuffer(raw[5 : 5 + 2 * size * size], dtype="<u2").reshape(size, size)
    assert np.array_equal(png[::-1], ter), "PNG is north-up; .ter row 0 is the south edge"


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_scene_tree_parents_and_terrain_block(map_key: str) -> None:
    root = require_built(map_key)
    spec = load_spec(map_key)
    handoff = json.loads((PACK_ROOT / map_key / "authoring" / f"{spec.MOD_ID}.handoff.json").read_text())
    items = all_items(root / "main")
    names = {obj["name"] for _, obj in items}
    for path, obj in items:
        assert "class" in obj and "name" in obj, (path, obj)
        if obj["name"] != "MissionGroup":
            assert obj.get("__parent") in names, (path, obj["name"])
        if obj["class"] == "SimGroup" and obj["name"] != "MissionGroup":
            folder = path.parent / obj["name"]
            assert (folder / "items.level.json").is_file(), f"SimGroup {obj['name']} has no folder"
    terrain = [obj for _, obj in items if obj["class"] == "TerrainBlock"]
    assert len(terrain) == 1
    block = terrain[0]
    footprint = spec.SITE["size_px"] * spec.SITE["square_size_m"]
    assert block["position"] == [-footprint / 2, -footprint / 2, 0]
    assert block["squareSize"] == spec.SITE["square_size_m"]
    assert block["maxHeight"] == handoff["terrain"]["max_height_m"]
    assert block["terrainFile"] == f"/levels/{spec.MOD_ID}/theTerrain.ter"
    assert (root / block["minimapImage"].split(f"{spec.MOD_ID}/", 1)[1]).is_file()
    for name in ("theLevelInfo", "tod", "sunsky"):
        assert name in names


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_info_json_spawns_resolve(map_key: str) -> None:
    root = require_built(map_key)
    info = json.loads((root / "info.json").read_text())
    items = all_items(root / "main")
    spawns = {obj["name"]: obj for _, obj in items if obj["class"] == "SpawnSphere"}
    listed = {s["objectname"] for s in info["spawnPoints"]}
    assert info["defaultSpawnPointName"] in listed
    assert listed == set(spawns), "info.json and PlayerDropPoints must agree"
    for entry in info["spawnPoints"]:
        assert (root / entry["preview"]).is_file()
    for preview in info["previews"]:
        assert (root / preview).is_file()
    assert info["size"] == [int(load_spec(map_key).SITE["size_px"] * load_spec(map_key).SITE["square_size_m"])] * 2
    assert "OpenStreetMap" in info["description"] and "3DEP" in info["description"]
    handoff = json.loads((PACK_ROOT / map_key / "authoring" / f"ericrolph_{map_key}.handoff.json").read_text())
    for spawn in spawns.values():
        assert 0.0 < spawn["position"][2] <= handoff["terrain"]["max_height_m"] + 1.0


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_terrain_materials_cover_every_layer(map_key: str) -> None:
    from PIL import Image

    root = require_built(map_key)
    spec = load_spec(map_key)
    footprint = spec.SITE["size_px"] * spec.SITE["square_size_m"]
    materials = json.loads((root / "art" / "terrains" / "main.materials.json").read_text())
    sets = [m for m in materials.values() if m["class"] == "TerrainMaterialTextureSet"]
    assert len(sets) == 1
    texture_set = sets[0]
    by_internal = {m["internalName"]: m for m in materials.values() if m["class"] == "TerrainMaterial"}
    assert set(by_internal) == set(spec.TERRAIN["materials"])
    expected_px = {"Base": texture_set["baseTexSize"][0], "Detail": texture_set["detailTexSize"][0], "Macro": texture_set["macroTexSize"][0]}
    for internal, entry in by_internal.items():
        assert entry["name"] == f"{internal}-{entry['persistentId']}"
        assert entry["groundmodelName"]
        for key, value in entry.items():
            if key.endswith("Tex"):
                path = root / value.split(f"/levels/{spec.MOD_ID}/", 1)[1]
                assert path.is_file(), value
                slot = "Base" if key.endswith("BaseTex") else "Detail" if key.endswith("DetailTex") else "Macro"
                assert Image.open(path).size == (expected_px[slot], expected_px[slot]), value
            if key.endswith("BaseTexSize"):
                assert value == int(footprint), "base texture must cover the footprint exactly once"


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_roads_are_inside_and_draped(map_key: str) -> None:
    root = require_built(map_key)
    spec = load_spec(map_key)
    handoff = json.loads((PACK_ROOT / map_key / "authoring" / f"{spec.MOD_ID}.handoff.json").read_text())
    half = spec.SITE["size_px"] * spec.SITE["square_size_m"] / 2
    road_materials = json.loads((root / "art" / "road" / "main.materials.json").read_text())
    roads = [obj for _, obj in all_items(root / "main") if obj["class"] == "DecalRoad"]
    assert len(roads) == handoff["roads"]["roads"]
    for road in roads:
        assert road["material"] in road_materials
        assert len(road["nodes"]) >= 2
        for x, y, z, width in road["nodes"]:
            assert -half <= x <= half and -half <= y <= half
            assert 0.0 <= z <= handoff["terrain"]["max_height_m"]
            assert 2.0 <= width <= 12.0
    for stage in road_materials[spec.ROADS["material"]["name"]]["Stages"][:1]:
        for value in stage.values():
            if isinstance(value, str) and value.startswith("/levels/"):
                assert (root / value.split(f"/levels/{spec.MOD_ID}/", 1)[1]).is_file(), value


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_distribution_zip_matches_lock(map_key: str) -> None:
    require_built(map_key)
    spec = load_spec(map_key)
    dist = PACK_ROOT / map_key / "dist"
    zip_path = dist / spec.ZIP_BASENAME
    lock_path = dist / f"{spec.MOD_ID}.lock.json"
    if not zip_path.is_file() or not lock_path.is_file():
        pytest.skip(f"{map_key}: dist not built")
    lock = json.loads(lock_path.read_text())
    assert sha256_file(zip_path) == lock["sha256"]
    assert zip_path.stat().st_size == lock["size"]
    _, _, _, packaging, _, _ = load_maplib()
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        assert len(members) == lock["members"]
        assert all(m.split("/")[0] in APPROVED_ROOTS for m in members)
        assert f"levels/{spec.MOD_ID}/info.json" in members
        assert f"levels/{spec.MOD_ID}/theTerrain.ter" in members
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        assert packaging.future_dated_members(archive) == []


@pytest.mark.parametrize("map_key", MAP_KEYS)
def test_design_ledger_matches_handoff(map_key: str) -> None:
    """The DESIGN.md ledger is generated from the handoff; a stale one is a red gate."""

    require_built(map_key)
    _, _, _, _, pipeline, _ = load_maplib()
    spec = load_spec(map_key)
    design = (PACK_ROOT / map_key / "DESIGN.md").read_text(encoding="utf-8")
    assert pipeline.LEDGER_HEADING in design
    rendered = pipeline.render_ledger(spec, PACK_ROOT / map_key)
    assert design[design.index(pipeline.LEDGER_HEADING) :] == rendered


# ---------------------------------------------------------------------------
# Delivery and local deployment tools
# ---------------------------------------------------------------------------


def _load_script(name: str):
    path = PACK_ROOT / f"{name}.py"
    loader = importlib.util.spec_from_file_location(f"beamng_maps_{name}", path)
    module = importlib.util.module_from_spec(loader)
    # dataclasses resolve string annotations through sys.modules[cls.__module__];
    # a module executed without being registered there breaks every @dataclass in it.
    sys.modules[loader.name] = module
    loader.loader.exec_module(module)
    return module


def _tiny_release(tmp_path: Path, key: str) -> Path:
    """A minimal but structurally valid level ZIP for the tooling gates."""

    zip_path = tmp_path / f"{key}_ericrolph.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(f"levels/ericrolph_{key}/info.json", json.dumps({"title": key}))
        archive.writestr(f"levels/ericrolph_{key}/theTerrain.ter", b"\x09" + b"\x00" * 64)
    return zip_path


def test_join_parts_rebuilds_zip_and_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    join_parts = _load_script("join_parts")
    pack = tmp_path / "pack"
    (pack / "meteor_crater").mkdir(parents=True)
    (pack / "meteor_crater" / "spec.py").write_text("MOD_ID='ericrolph_meteor_crater'\n")
    monkeypatch.setattr(join_parts, "PACK_ROOT", pack)
    original = _tiny_release(tmp_path, "meteor_crater")
    data = original.read_bytes()
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    chunks = [data[i : i + 40] for i in range(0, len(data), 40)]
    sums = []
    for index, chunk in enumerate(chunks):
        part = parts_dir / f"meteor_crater_ericrolph.zip.part{index}"
        part.write_bytes(chunk)
        sums.append(f"{hashlib.sha256(chunk).hexdigest()}  {part.name}")
    sums.append(f"{hashlib.sha256(data).hexdigest()}  meteor_crater_ericrolph.zip")
    (parts_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    assert join_parts.join(parts_dir) == 0
    rebuilt = pack / "meteor_crater" / "dist" / "meteor_crater_ericrolph.zip"
    assert rebuilt.read_bytes() == data
    lock = json.loads((pack / "meteor_crater" / "dist" / "ericrolph_meteor_crater.lock.json").read_text())
    assert lock["sha256"] == hashlib.sha256(data).hexdigest() and lock["members"] == 2
    # A corrupted part is refused and nothing is left behind.
    (parts_dir / "meteor_crater_ericrolph.zip.part0").write_bytes(b"x" * 40)
    rebuilt.unlink()
    assert join_parts.join(parts_dir) == 1
    assert not rebuilt.exists()


def test_deploy_local_reports_and_deploys_into_a_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy_local = _load_script("deploy_local")
    pack = tmp_path / "pack"
    (pack / "meteor_crater" / "dist").mkdir(parents=True)
    (pack / "meteor_crater" / "spec.py").write_text(
        "MOD_ID='ericrolph_meteor_crater'\nDISPLAY_NAME='Crater'\nZIP_BASENAME='meteor_crater_ericrolph.zip'\n"
    )
    release = _tiny_release(pack / "meteor_crater" / "dist", "meteor_crater")
    lock = {"sha256": hashlib.sha256(release.read_bytes()).hexdigest()}
    (pack / "meteor_crater" / "dist" / "ericrolph_meteor_crater.lock.json").write_text(json.dumps(lock))
    profile = tmp_path / "profile"
    (profile / "mods").mkdir(parents=True)
    monkeypatch.setattr(deploy_local, "PACK_ROOT", pack)
    monkeypatch.setenv("BEAMNG_MAPS_PROFILE", str(profile))
    monkeypatch.setenv("BEAMNG_MAPS_ALLOW_RUNNING", "1")
    assert deploy_local.main([]) == 1  # missing -> stale report exits 1
    assert deploy_local.main(["--deploy"]) == 0
    deployed = profile / "mods" / "meteor_crater_ericrolph.zip"
    assert deployed.read_bytes() == release.read_bytes()
    assert deploy_local.main([]) == 0  # current
    # A second copy of the namespace anywhere below mods/ is a conflict, by content.
    shadow = profile / "mods" / "repo" / "old_copy.zip"
    shadow.parent.mkdir()
    shutil.copyfile(release, shadow)
    assert deploy_local.main(["--deploy"]) == 1
    # A dist that disagrees with its lock is never deployed.
    shadow.unlink()
    release.write_bytes(release.read_bytes() + b"\x00")
    assert deploy_local.main(["--deploy"]) == 1


def test_install_local_rejoins_parts_and_deploys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """install_local --parts must take a delivered build straight into the profile, no rebuild."""

    install_local = _load_script("install_local")
    pack = tmp_path / "pack"
    (pack / "meteor_crater").mkdir(parents=True)
    (pack / "meteor_crater" / "spec.py").write_text(
        "MOD_ID='ericrolph_meteor_crater'\nDISPLAY_NAME='Crater'\nZIP_BASENAME='meteor_crater_ericrolph.zip'\n"
    )
    for module in (install_local.build, install_local.join_parts, install_local.deploy_local):
        monkeypatch.setattr(module, "PACK_ROOT", pack)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(install_local.build, "run_stage", lambda key, stage, force=False: calls.append((key, stage)))
    data = _tiny_release(tmp_path, "meteor_crater").read_bytes()
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    (parts_dir / "meteor_crater_ericrolph.zip.part0").write_bytes(data)
    (parts_dir / "SHA256SUMS.txt").write_text(f"{hashlib.sha256(data).hexdigest()}  meteor_crater_ericrolph.zip\n")
    profile = tmp_path / "profile"
    (profile / "mods").mkdir(parents=True)
    monkeypatch.setenv("BEAMNG_MAPS_PROFILE", str(profile))
    monkeypatch.setenv("BEAMNG_MAPS_ALLOW_RUNNING", "1")
    assert install_local.main(["--parts", str(parts_dir)]) == 0
    assert calls == [], "a verified delivered build must not trigger a rebuild"
    assert (profile / "mods" / "meteor_crater_ericrolph.zip").read_bytes() == data
    # Without parts and without a release, every stage runs (stubbed here) and the
    # missing lock is reported rather than silently deployed.
    (pack / "meteor_crater" / "dist" / "meteor_crater_ericrolph.zip").unlink()
    with pytest.raises(SystemExit):
        install_local.main(["--no-deploy"])
    assert [stage for _, stage in calls] == ["fetch", "terrain", "level", "dist"]


def test_install_local_release_download_verifies_and_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--release pulls each ZIP from the release, checks it against SHA256SUMS.txt, writes the lock."""

    install_local = _load_script("install_local")
    pack = tmp_path / "pack"
    (pack / "meteor_crater").mkdir(parents=True)
    (pack / "meteor_crater" / "spec.py").write_text(
        "MOD_ID='ericrolph_meteor_crater'\nDISPLAY_NAME='Crater'\nZIP_BASENAME='meteor_crater_ericrolph.zip'\n"
    )
    for module in (install_local.build, install_local.join_parts, install_local.deploy_local):
        monkeypatch.setattr(module, "PACK_ROOT", pack)
    data = _tiny_release(tmp_path, "meteor_crater").read_bytes()
    served = {
        "SHA256SUMS.txt": f"{hashlib.sha256(data).hexdigest()}  meteor_crater_ericrolph.zip\n".encode(),
        "meteor_crater_ericrolph.zip": data,
    }
    requested: list[str] = []

    def fake_download(url: str, path: Path) -> None:
        requested.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(served[url.rsplit("/", 1)[1]])

    install_local.fetch_release("beamng-maps-v1", ["meteor_crater"], repo="o/r", download=fake_download)
    assert requested == [
        "https://github.com/o/r/releases/download/beamng-maps-v1/SHA256SUMS.txt",
        "https://github.com/o/r/releases/download/beamng-maps-v1/meteor_crater_ericrolph.zip",
    ]
    dist = pack / "meteor_crater" / "dist"
    assert (dist / "meteor_crater_ericrolph.zip").read_bytes() == data
    lock = json.loads((dist / "ericrolph_meteor_crater.lock.json").read_text())
    assert lock["sha256"] == hashlib.sha256(data).hexdigest() and "beamng-maps-v1" in lock["origin"]
    # A tampered asset is deleted, never locked.
    served["meteor_crater_ericrolph.zip"] = data + b"\x00"
    (dist / "meteor_crater_ericrolph.zip").unlink()
    with pytest.raises(SystemExit):
        install_local.fetch_release("beamng-maps-v1", ["meteor_crater"], repo="o/r", download=fake_download)
    assert not (dist / "meteor_crater_ericrolph.zip").exists()
