# BeamNG maps pack: six real landscapes from public GIS data

Six BeamNG.drive levels whose terrain is measured, not sculpted: every heightmap sample
comes from public airborne lidar, every ground colour from public orthoimagery, every
road centreline from OpenStreetMap. Built on the same evidence chain as the Giant Props
pack (`beamng-mcp/examples/giant_props`): a deterministic generator owns every number,
an authoring handoff JSON is the single source of truth the tests hash against, and
every file the game reads is generated, never hand-edited.

| Map key | Level | Footprint | Sample | Elevation sources | The bit |
| --- | --- | --- | --- | --- | --- |
| `meteor_crater` | Barringer Meteor Crater | 2048 m | 0.5 m | NCALM 0.25 m lidar (OpenTopography) over USGS 3DEP 1 m | A 1.2 km, 170 m deep impact bowl: rim strata, talus aprons, ejecta ripples. Perimeter runs, scree climbs, rim drops. |
| `wallace_creek` | Carrizo Plain - Wallace Creek | 4096 m | 1 m | B4 0.5 m lidar (OpenTopography) over USGS 3DEP 1 m | The San Andreas surface trace: the 130 m offset channel, sag ponds, pressure ridges, scarps. Trophy-truck country. |
| `factory_butte` | Factory Butte Badlands | 4096 m | 1 m | Utah statewide 1 m lidar via USGS 3DEP | Mancos Shale rills, clay fins and mud-wash flats. Natural half-pipes and spine transfers. |
| `mt_st_helens` | Mount St. Helens Pumice Plain | 6144 m | 1.5 m | USGS 3DEP 1 m (2018 lidar) | The 1980 crater headwall, the lava dome, braided ash canyons down to Spirit Lake. |
| `black_bear_pass` | Black Bear Pass | 4096 m | 1 m | USGS 3DEP 1 m (2020 lidar) | 3,913 m summit, one-way shelf road, the Steps, switchbacks above Bridal Veil Falls. |
| `bingham_canyon` | Bingham Canyon Mine | 6144 m | 1.5 m | USGS 3DEP 1 m (2023 lidar) | An inverted mountain: 15 m benches spiralling 1.2 km down, linked by continuous haul roads. |

None of the six has a building, a tree or a guardrail to model. That is the point: the
soft-body physics engine gets a measured surface and nothing else in the way.

## The process (the five GIS steps, automated)

The manual workflow the pack replaces is: acquire a DEM and orthophotos, crop a square
power-of-two footprint in QGIS, export a 16-bit heightmap, import it in the World
Editor, then lay roads and textures. Each step is a stage of `build.py`:

1. **fetch** (`maplib/gis_sources.py`): USGS 3DEP is exported straight from the
   `3DEPElevation` image service as float32 GeoTIFF tiles in the level's own UTM zone.
   The OpenTopography raster bucket is a plain S3 listing, so the B4 tiles are fetched
   by name and the 2.3 GB NCALM Meteor Crater grid is downloaded once, windowed to the
   footprint and deleted. NAIP orthoimagery comes from the USGS NAIP image service, and
   road centrelines from an Overpass mirror. Everything lands in `<map>/data/`, cached
   and re-validated by opening the file, never by trusting its presence.
2. **terrain** (`maplib/heightmap.py`): every source is resampled onto the level grid
   (area-average when downsampling lidar, bilinear otherwise), the lidar grid is levelled
   onto the 3DEP datum by the median offset in the overlap, composited with a feathered
   edge, holes are filled by nearest neighbour, single-sample lidar spikes are clamped,
   and a layer map is painted from slope and elevation rules in the spec.
3. **level** (`maplib/level_builder.py`): heights are encoded as u16 relative to the
   lowest sample with `maxHeight` sized to the real relief (0.3 cm steps on the crater,
   1.7 cm on the pass), written as a version-9 `theTerrain.ter` **and** as the 16-bit
   `theTerrain.terrainheightmap.png` the Import Terrain tool accepts. The level tree
   (`info.json`, `main/` scene files, terrain materials, the decal-road material, spawn
   points, previews, minimap) is generated from the spec.
4. **dist** (`maplib/packaging.py`): a `ZIP_STORED` archive with only approved BeamNG
   roots, monotonic never-in-the-future member timestamps and a SHA-256 lock.

```bash
pip install -r beamng_maps/requirements.txt
python beamng_maps/build.py --list
python beamng_maps/build.py meteor_crater all        # fetch -> terrain -> level -> dist
python beamng_maps/build.py --all all                # every map
python -m pytest -q tests/test_beamng_maps_pack.py   # static gates
```

## Getting the maps into your game

The level ZIPs (80-90 MiB each) are build output, not repository content. Two ways to
have them locally:

1. **Rejoin a delivered build.** A build handed over from a session arrives as
   `<key>_ericrolph.zip.partN` pieces plus `SHA256SUMS.txt` (whole ZIPs exceed the
   30 MiB delivery limit). Put every part and the sums file in one folder, then:

   ```powershell
   python beamng_maps\join_parts.py C:\path\to\downloaded_parts
   ```

   That verifies each part and each rejoined ZIP against `SHA256SUMS.txt`, writes the
   ZIPs to `beamng_maps\<key>\dist\` and writes their release locks. A mismatch deletes
   the ZIP rather than leaving something unverifiable to install.

2. **Rebuild from the public data.** `python beamng_maps\build.py --all all` downloads
   about 3 GB (2.3 GB of it the Meteor Crater lidar grid) and rebuilds everything;
   allow ten to fifteen minutes.

Then deploy, with BeamNG closed:

```powershell
python beamng_maps\deploy_local.py            # report: missing / stale / current per map
python beamng_maps\deploy_local.py --deploy   # copy what is stale into the play profile, hash-verified
```

`deploy_local.py` targets `%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods\` (set
`BEAMNG_MAPS_PROFILE` to the profile root to override), refuses to run while the game
is open, and refuses if any other zip below `mods\` already carries one of the
`levels/ericrolph_<key>/` namespaces (BeamNG mounts every zip recursively, so a stale
copy shadows the release). Launch BeamNG.drive, then Freeroam > Select Level: the six
levels are listed under their display names (Barringer Meteor Crater, Carrizo Plain -
Wallace Creek, Factory Butte Badlands, Mount St. Helens Pumice Plain, Black Bear Pass,
Bingham Canyon Mine), each with three spawn points.

If a level does not appear after deployment, the first place to look is
`%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\beamng.log` for lines mentioning
`ericrolph_`; that log says whether the zip was mounted and whether `info.json` or
the terrain failed to load.

## Layout

- `maplib/`: shared toolkit (`gis_sources.py`, `heightmap.py`, `texture_kit.py`,
  `level_builder.py`, `packaging.py`, `pipeline.py`).
- `build.py` (stages), `join_parts.py` (rejoin a delivered build), `deploy_local.py`
  (verified sync into the play profile).
- `<map_key>/spec.py`: the map's authored constants: site centre, UTM zone, sample size,
  data sources with citations, terrain materials and slope rules, road widths, spawns,
  time of day and the selector copy. The generator consumes only this.
- `<map_key>/DESIGN.md`: the blueprint and the build ledger (what the data measured).
- `<map_key>/authoring/`: `<mod_id>.handoff.json` (footprint, sources, terrain stats,
  spawn coordinates, roads, SHA-256 of every shipped terrain file) and the thumbnail.
  Tracked: this is the evidence.
- `<map_key>/data/`, `mod/`, `dist/`: downloads, the generated level tree and the ZIP.
  Not tracked (up to 2 GB of public data per map); rebuilt by `build.py`.

## Terrain conventions that are easy to get wrong

- **`.ter` layout (version 9)**: u8 version, u32 size, u16 heights, u8 layer indices,
  u32 count, then material internal names each prefixed by a u8 length. Verified against
  a shipped level's binary. Version 8 files carry an extra `size * size * 4` byte block
  between the layer map and the names; version 9 does not.
- **Height scale**: `metres = stored * maxHeight / 65536`. The pack sets `maxHeight` to
  the real relief plus 1 %, so precision is spent on terrain that exists.
- **Grid order**: the `.ter` starts at the TerrainBlock position (south-west corner) and
  runs east then north. The exported `terrainheightmap.png` is written north-up like any
  map image. If a manual Import Terrain of the PNG comes out mirrored north-south, flip
  the image vertically; the `.ter` the pack ships is already correct and authoritative.
- **Base texture size**: a TerrainMaterial's `*BaseTexSize` is world metres, not pixels
  (a shipped 2048 m level sets 2048 while its texture set declares 2048 pixels). The pack
  sets it to the footprint so the orthoimagery covers the level exactly once.
- **Vehicle heading**: vehicles spawn nose toward the spawn marker's -Y, so a compass
  heading of 0 (north) is a 180-degree marker yaw.

## Data sources and licences

- USGS 3DEP elevation (public domain, U.S. Geological Survey).
- NCALM Meteor Crater lidar, Palucis 2010, OpenTopography `OTSDEM.112011.26912.3`,
  https://doi.org/10.5069/G9V40S4C (freely available; cite the DOI).
- B4 Project lidar, Southern San Andreas and San Jacinto faults 2005, USGS/NSF/NCALM,
  OpenTopography `OTSDEM.032018.32611.1`, https://doi.org/10.5066/F7TQ5ZQ6 (public domain).
- NAIP orthoimagery via The National Map (public domain, USDA/USGS).
- Road centrelines (c) OpenStreetMap contributors, ODbL 1.0.

Each level's `info.json` description carries this attribution.

## What is and is not verified

The static gates prove the artefacts: header, size, material names, layer indices and
heightmap rows of the `.ter`; the PNG heightmap is 16-bit and row-consistent with it;
every scene object parses and its parent exists; every referenced texture ships; the
ZIP matches its lock. Live behaviour (the level loading in BeamNG, decal roads draping,
material blending) has not yet been exercised on a game install from this pack; the
first live run is the next step, per the giant props law that a green static suite is
not a play-test.
