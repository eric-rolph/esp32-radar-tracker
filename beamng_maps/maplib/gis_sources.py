"""Public-data fetchers for the BeamNG maps pack.

Every source here is free and publicly downloadable without an account:

- **USGS 3DEP** (``3DEPElevation`` ImageServer) - the national best-available bare-earth
  DEM, 1 m where lidar exists. Public domain. Exported as float32 GeoTIFF tiles in the
  level's own UTM zone, so no reprojection guesswork happens later.
- **OpenTopography raster bucket** (``opentopography.s3.sdsc.edu/raster``) - the
  hosted lidar-derived grids (NCALM Meteor Crater at 0.25 m, the B4 San Andreas
  survey at 0.5 m). The bucket is a plain S3 listing, so tiles are fetched by name and
  large single grids are read through GDAL's ``/vsicurl/`` with HTTP range requests.
- **USGS National Map orthoimagery** (NAIP) - public-domain aerial imagery for the
  ground colour overlay and the preview thumbnail.
- **OpenStreetMap** via an Overpass mirror - road centrelines (ODbL, attributed in the
  level's info.json and listing copy).

Every fetch is cached under ``<map>/data/`` (gitignored) and re-validated by opening
the file, never by trusting its presence: a half-written GeoTIFF from an interrupted
run must not silently become a hole in the terrain.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import requests

USGS_3DEP_EXPORT = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
)
USGS_NAIP_EXPORT = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
)
OT_RASTER_BUCKET = "https://opentopography.s3.sdsc.edu/raster"
OVERPASS_ENDPOINTS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "beamng-maps-pack/1.0 (public GIS to BeamNG terrain; eric-rolph)"

Log = Callable[[str], None]


def _log_default(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
# Footprint: the square the level covers, in the level's UTM zone.
# ---------------------------------------------------------------------------


def utm_epsg_for(lon: float, lat: float) -> int:
    """WGS84 UTM zone EPSG for a point (northern hemisphere only - every site here)."""

    zone = int((lon + 180.0) // 6.0) + 1
    if lat < 0:
        return 32700 + zone
    return 32600 + zone


@dataclass(frozen=True)
class Footprint:
    """An axis-aligned square in a projected CRS, west/south snapped to whole metres."""

    epsg: int
    west: float
    south: float
    size_m: float

    @property
    def east(self) -> float:
        return self.west + self.size_m

    @property
    def north(self) -> float:
        return self.south + self.size_m

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    @property
    def center(self) -> tuple[float, float]:
        return (self.west + self.size_m / 2.0, self.south + self.size_m / 2.0)

    def buffered(self, margin_m: float) -> "Footprint":
        return Footprint(self.epsg, self.west - margin_m, self.south - margin_m, self.size_m + 2 * margin_m)

    @classmethod
    def from_center(cls, lat: float, lon: float, epsg: int, size_m: float) -> "Footprint":
        from rasterio.warp import transform

        xs, ys = transform("EPSG:4326", f"EPSG:{epsg}", [lon], [lat])
        west = math.floor(xs[0] - size_m / 2.0)
        south = math.floor(ys[0] - size_m / 2.0)
        return cls(epsg, float(west), float(south), float(size_m))

    def wgs84_bbox(self, margin_m: float = 0.0) -> tuple[float, float, float, float]:
        """(south, west, north, east) in degrees, from corners AND edge midpoints.

        UTM edges bow slightly in lat/lon; the midpoints keep the box conservative.
        """

        from rasterio.warp import transform

        fp = self.buffered(margin_m)
        cx, cy = fp.center
        xs = [fp.west, fp.east, fp.east, fp.west, cx, cx, fp.west, fp.east]
        ys = [fp.south, fp.south, fp.north, fp.north, fp.south, fp.north, cy, cy]
        lons, lats = transform(f"EPSG:{fp.epsg}", "EPSG:4326", xs, ys)
        return (min(lats), min(lons), max(lats), max(lons))

    def to_json(self) -> dict:
        return {"epsg": self.epsg, "west": self.west, "south": self.south, "size_m": self.size_m}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _get(
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    timeout: float = 300.0,
    retries: int = 4,
    log: Log = _log_default,
) -> requests.Response:
    delay = 2.0
    last: Exception | None = None
    with _session() as session:
        for attempt in range(retries + 1):
            try:
                if data is not None:
                    response = session.post(url, data=data, timeout=timeout)
                else:
                    response = session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: BLE001 - every transport failure retries
                last = exc
                if attempt == retries:
                    break
                log(f"  retry {attempt + 1}/{retries} after {type(exc).__name__}: {str(exc)[:120]}")
                time.sleep(delay)
                delay *= 2.0
    raise RuntimeError(f"fetch failed after {retries} retries: {url}") from last


def _raster_ok(path: Path, expect_shape: tuple[int, int] | None = None) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            if expect_shape is not None and (dataset.height, dataset.width) != expect_shape:
                return False
            dataset.read(1, window=((0, 1), (0, 1)))
        return True
    except Exception:  # noqa: BLE001 - any unreadable file is "not cached"
        return False


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# USGS 3DEP elevation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tile:
    """One export request: a rectangle (the last row/column of a grid may be short)."""

    epsg: int
    west: float
    south: float
    width_m: float
    height_m: float

    @property
    def east(self) -> float:
        return self.west + self.width_m

    @property
    def north(self) -> float:
        return self.south + self.height_m

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)


def tile_grid(fp: Footprint, tile_m: float) -> list[tuple[int, int, Tile]]:
    """Tiles covering ``fp`` from its south-west corner.

    Width and height are clipped INDEPENDENTLY. The first version clipped both to the
    smaller remaining extent, so the partial strip along the north and east edges of a
    buffered footprint came back as a 128 x 128 corner instead of a 2048 x 128 strip,
    and the rest of the strip was never requested: a 64 m band of nearest-neighbour
    fill along two edges of every 3DEP-only map.
    """

    count = int(math.ceil(fp.size_m / tile_m))
    tiles = []
    for iy in range(count):
        for ix in range(count):
            west = fp.west + ix * tile_m
            south = fp.south + iy * tile_m
            width = min(tile_m, fp.east - west)
            height = min(tile_m, fp.north - south)
            tiles.append((ix, iy, Tile(fp.epsg, west, south, width, height)))
    return tiles


def fetch_3dep_tiles(
    fp: Footprint,
    out_dir: Path,
    *,
    resolution: float = 1.0,
    tile_px: int = 2048,
    margin_m: float = 64.0,
    force: bool = False,
    log: Log = _log_default,
) -> list[Path]:
    """Float32 GeoTIFF tiles of the 3DEP best-available DEM in the footprint's UTM zone."""

    out_dir.mkdir(parents=True, exist_ok=True)
    area = fp.buffered(margin_m)
    tile_m = tile_px * resolution
    paths = []
    for ix, iy, tile in tile_grid(area, tile_m):
        width = int(round(tile.width_m / resolution))
        height = int(round(tile.height_m / resolution))
        path = out_dir / f"3dep_{resolution:g}m_E{int(tile.west):07d}_N{int(tile.south):08d}.tif"
        paths.append(path)
        if not force and _raster_ok(path, (height, width)):
            continue
        log(f"  3DEP tile {ix},{iy} {width}x{height}px @ {resolution:g} m -> {path.name}")
        params = {
            "bbox": f"{tile.west},{tile.south},{tile.east},{tile.north}",
            "bboxSR": tile.epsg,
            "imageSR": tile.epsg,
            "size": f"{width},{height}",
            "format": "tiff",
            "pixelType": "F32",
            "noData": "-999999",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "image",
        }
        response = _get(USGS_3DEP_EXPORT, params=params, log=log)
        if response.headers.get("Content-Type", "").startswith("application/json"):
            raise RuntimeError(f"3DEP export error: {response.text[:300]}")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(response.content)
        if not _raster_ok(tmp, (height, width)):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"3DEP export returned an unreadable tile for {path.name}")
        tmp.replace(path)
    _write_manifest(
        out_dir / "3dep.manifest.json",
        {
            "source": "USGS 3DEP (3DEPElevation ImageServer exportImage)",
            "url": USGS_3DEP_EXPORT,
            "license": "Public domain (U.S. Geological Survey)",
            "footprint": area.to_json(),
            "resolution_m": resolution,
            "tiles": [p.name for p in paths],
        },
    )
    return paths


# ---------------------------------------------------------------------------
# USGS NAIP orthoimagery (The National Map "USGS Imagery Only")
# ---------------------------------------------------------------------------


def fetch_naip_tiles(
    fp: Footprint,
    out_dir: Path,
    *,
    resolution: float = 1.0,
    tile_px: int = 2048,
    force: bool = False,
    log: Log = _log_default,
) -> list[Path]:
    """PNG tiles (with JSON bounds sidecars) of public-domain USGS orthoimagery."""

    out_dir.mkdir(parents=True, exist_ok=True)
    tile_m = tile_px * resolution
    paths = []
    for ix, iy, tile in tile_grid(fp, tile_m):
        width = int(round(tile.width_m / resolution))
        height = int(round(tile.height_m / resolution))
        path = out_dir / f"naip_{resolution:g}m_E{int(tile.west):07d}_N{int(tile.south):08d}.png"
        sidecar = path.with_suffix(".json")
        paths.append(path)
        if not force and path.is_file() and sidecar.is_file() and path.stat().st_size > 0:
            try:
                cached = json.loads(sidecar.read_text())
                if cached.get("size_px") == [width, height]:
                    continue
            except Exception:  # noqa: BLE001 - a bad sidecar is a cache miss
                pass
        log(f"  NAIP tile {ix},{iy} {width}x{height}px @ {resolution:g} m -> {path.name}")
        params = {
            "bbox": f"{tile.west},{tile.south},{tile.east},{tile.north}",
            "bboxSR": tile.epsg,
            "imageSR": tile.epsg,
            "size": f"{width},{height}",
            "format": "png",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "image",
        }
        response = _get(USGS_NAIP_EXPORT, params=params, log=log)
        if not response.content.startswith(b"\x89PNG"):
            raise RuntimeError(f"NAIP export did not return a PNG for {path.name}: {response.text[:200]}")
        path.write_bytes(response.content)
        _write_manifest(
            sidecar,
            {
                "epsg": tile.epsg,
                "bounds": list(tile.bounds),
                "size_px": [width, height],
                "resolution_m": resolution,
                "source": "USGS The National Map: Orthoimagery (USGSNAIPImagery ImageServer)",
                "license": "Public domain (USDA NAIP / USGS)",
            },
        )
    return paths


# ---------------------------------------------------------------------------
# OpenTopography hosted rasters
# ---------------------------------------------------------------------------


def list_ot_bucket(prefix: str, *, log: Log = _log_default) -> list[tuple[str, int]]:
    """Every (key, size) under ``prefix`` in the public OpenTopography raster bucket."""

    namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    keys: list[tuple[str, int]] = []
    marker: str | None = None
    while True:
        params = {"prefix": prefix, "max-keys": 1000}
        if marker:
            params["marker"] = marker
        response = _get(OT_RASTER_BUCKET, params=params, log=log, timeout=120)
        root = ET.fromstring(response.text)
        for item in root.findall("s3:Contents", namespace):
            keys.append((item.find("s3:Key", namespace).text, int(item.find("s3:Size", namespace).text)))
        truncated = root.find("s3:IsTruncated", namespace)
        if truncated is None or truncated.text != "true":
            break
        next_marker = root.find("s3:NextMarker", namespace)
        marker = next_marker.text if next_marker is not None else keys[-1][0]
    return keys


def fetch_ot_tiles(
    prefix: str,
    fp: Footprint,
    out_dir: Path,
    *,
    pattern: str,
    tile_m: float,
    margin_m: float = 64.0,
    force: bool = False,
    log: Log = _log_default,
) -> list[Path]:
    """Download the bucket tiles whose named origin square intersects the footprint.

    ``pattern`` must capture the tile's easting and northing origin (metres) as groups 1
    and 2, e.g. ``r"b4_(\\d+)_(\\d+)_be\\.tif$"`` for the B4 survey.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    area = fp.buffered(margin_m)
    regex = re.compile(pattern)
    wanted = []
    for key, size in list_ot_bucket(prefix, log=log):
        match = regex.search(key)
        if not match:
            continue
        east0, north0 = float(match.group(1)), float(match.group(2))
        if east0 + tile_m <= area.west or east0 >= area.east:
            continue
        if north0 + tile_m <= area.south or north0 >= area.north:
            continue
        wanted.append((key, size))
    paths = []
    for key, size in sorted(wanted):
        path = out_dir / Path(key).name
        paths.append(path)
        if not force and path.is_file() and path.stat().st_size == size and _raster_ok(path):
            continue
        log(f"  OpenTopography tile {Path(key).name} ({size / 1e6:.1f} MB)")
        response = _get(f"{OT_RASTER_BUCKET}/{key}", log=log, timeout=900)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(response.content)
        if len(response.content) != size or not _raster_ok(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"OpenTopography tile {key} arrived truncated or unreadable")
        tmp.replace(path)
    _write_manifest(
        out_dir / f"{prefix.strip('/').split('/')[0]}.manifest.json",
        {
            "source": f"OpenTopography raster bucket {OT_RASTER_BUCKET}/{prefix}",
            "footprint": area.to_json(),
            "tiles": [p.name for p in paths],
        },
    )
    return paths


def _download(url: str, path: Path, expected_size: int, *, log: Log = _log_default) -> Path:
    """Streaming download with resume; verified by size, never by presence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size == expected_size:
        return path
    tmp = path.with_suffix(path.suffix + ".part")
    delay = 2.0
    for attempt in range(6):
        have = tmp.stat().st_size if tmp.is_file() else 0
        if have > expected_size:
            tmp.unlink()
            have = 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with requests.get(url, headers=headers, stream=True, timeout=300) as response:
                if have and response.status_code != 206:
                    tmp.unlink(missing_ok=True)
                    have = 0
                response.raise_for_status()
                with tmp.open("ab" if have else "wb") as sink:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        sink.write(chunk)
            if tmp.stat().st_size == expected_size:
                tmp.replace(path)
                return path
            log(f"  {path.name}: got {tmp.stat().st_size} of {expected_size} bytes, resuming")
        except Exception as exc:  # noqa: BLE001 - resume on any transport failure
            log(f"  {path.name}: {type(exc).__name__}: {str(exc)[:100]} (retry {attempt + 1})")
        time.sleep(delay)
        delay *= 2.0
    raise RuntimeError(f"could not download {url}")


def fetch_ot_grid_window(
    grid_prefix: str,
    open_name: str,
    fp: Footprint,
    out_path: Path,
    *,
    cache_dir: Path,
    margin_m: float = 64.0,
    keep_cache: bool = False,
    force: bool = False,
    log: Log = _log_default,
) -> Path:
    """Window one large hosted grid down to the footprint, as a float32 GeoTIFF.

    The NCALM Meteor Crater grid is a 24001 x 24001 ArcInfo binary grid (2.3 GB in
    ``w001001.adf``). GDAL can read it over HTTP with ``/vsicurl/``, but the grid's
    4-row tiles turn a footprint window into tens of thousands of range requests
    (measured: 127 s per 512 rows). The bucket streams at ~40 MB/s, so the honest
    path is to download the grid directory once, window it locally, and delete it.
    """

    if not force and _raster_ok(out_path):
        return out_path
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    out_path.parent.mkdir(parents=True, exist_ok=True)
    area = fp.buffered(margin_m)
    grid_dir = cache_dir / grid_prefix.strip("/").split("/")[-1]
    entries = list_ot_bucket(grid_prefix, log=log)
    if not entries:
        raise RuntimeError(f"no objects under {grid_prefix} in the OpenTopography bucket")
    total = sum(size for _, size in entries)
    log(f"  OpenTopography grid {grid_prefix}: {len(entries)} files, {total / 1e9:.2f} GB")
    for key, size in entries:
        _download(f"{OT_RASTER_BUCKET}/{key}", grid_dir / Path(key).name, size, log=log)
    with rasterio.open(grid_dir / open_name) as source:
        if source.crs is None:
            raise RuntimeError(f"hosted grid has no CRS: {grid_prefix}")
        src_bounds = transform_bounds(f"EPSG:{area.epsg}", source.crs, *area.bounds)
        window = from_bounds(*src_bounds, transform=source.transform).round_offsets().round_lengths()
        log(f"  window {int(window.width)}x{int(window.height)} px @ {source.res[0]:g} m")
        data = source.read(1, window=window, masked=True).filled(np.nan).astype("float32")
        profile = {
            "driver": "GTiff",
            "dtype": "float32",
            "count": 1,
            "width": data.shape[1],
            "height": data.shape[0],
            "crs": source.crs,
            "transform": source.window_transform(window),
            "nodata": -999999.0,
            "compress": "deflate",
            "predictor": 3,
            "tiled": True,
        }
    tmp = out_path.with_suffix(".part")
    data = np.where(np.isfinite(data), data, -999999.0).astype("float32")
    with rasterio.open(tmp, "w", **profile) as sink:
        sink.write(data, 1)
    tmp.replace(out_path)
    if not keep_cache:
        for child in grid_dir.iterdir():
            child.unlink()
        grid_dir.rmdir()
    return out_path


# ---------------------------------------------------------------------------
# OpenStreetMap roads
# ---------------------------------------------------------------------------


def fetch_osm_roads(
    fp: Footprint,
    out_path: Path,
    *,
    margin_m: float = 100.0,
    force: bool = False,
    log: Log = _log_default,
) -> Path:
    """Every ``highway`` way (with geometry) inside the footprint, as raw Overpass JSON."""

    if not force and out_path.is_file() and out_path.stat().st_size > 0:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    south, west, north, east = fp.wgs84_bbox(margin_m)
    query = (
        "[out:json][timeout:180];"
        f'(way["highway"]({south:.6f},{west:.6f},{north:.6f},{east:.6f}););'
        "out geom;"
    )
    last: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            log(f"  Overpass {endpoint.split('/')[2]} ...")
            response = _get(endpoint, data={"data": query}, retries=1, timeout=240, log=log)
            payload = response.json()
            if "elements" not in payload:
                raise RuntimeError("no elements in Overpass response")
            payload["_query"] = query
            payload["_endpoint"] = endpoint
            payload["_license"] = "OpenStreetMap contributors, ODbL 1.0"
            out_path.write_text(json.dumps(payload), encoding="utf-8")
            log(f"  {len(payload['elements'])} ways")
            return out_path
        except Exception as exc:  # noqa: BLE001 - fall through to the next mirror
            last = exc
            log(f"  {endpoint.split('/')[2]} failed: {str(exc)[:120]}")
    raise RuntimeError("every Overpass endpoint failed") from last
