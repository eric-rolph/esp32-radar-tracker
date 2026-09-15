"""DEM compositing, resampling and encoding for BeamNG terrain.

The pipeline is: mosaic the 3DEP baseline -> resample every source onto the level grid
(area-average when downsampling lidar, bilinear when upsampling) -> level the lidar
grid onto the 3DEP datum with the median offset in the overlap -> composite with a
feathered edge -> fill any remaining holes by nearest neighbour -> encode.

BeamNG stores terrain as u16 with ``heightMeters = stored * maxHeight / 65536`` and the
grid index ``x + y * size`` starting at the TerrainBlock position (south-west corner,
y increasing north). Everything here keeps arrays in NORTH-UP image order (row 0 =
north) and flips once, at encode time, so the two conventions never mix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

NODATA = -999999.0


@dataclass
class Grid:
    """A north-up float32 elevation array on the level's grid."""

    data: np.ndarray  # (size, size) float32, NaN = no data
    epsg: int
    west: float
    north: float
    res: float

    @property
    def size(self) -> int:
        return int(self.data.shape[0])

    @property
    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(self.west, self.north, self.res, self.res)


def target_grid(fp, size_px: int, res: float) -> Grid:
    return Grid(np.full((size_px, size_px), np.nan, dtype="float32"), fp.epsg, fp.west, fp.north, res)


def _open_all(paths: list[Path]):
    import rasterio

    return [rasterio.open(p) for p in paths]


def resample_sources(paths: list[Path], grid: Grid, *, downsample: bool) -> np.ndarray:
    """Reproject every raster in ``paths`` onto ``grid`` and return a NaN-masked mosaic.

    ``downsample=True`` uses area averaging (right for 0.25 m lidar -> 0.5 m samples);
    otherwise bilinear. Tiles are merged first so seams resample once.
    """

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from rasterio.warp import reproject

    if not paths:
        return np.full(grid.data.shape, np.nan, dtype="float32")
    datasets = _open_all(paths)
    try:
        if len(datasets) == 1:
            source = datasets[0].read(1, masked=True).filled(np.nan).astype("float32")
            src_transform = datasets[0].transform
            src_crs = datasets[0].crs
        else:
            mosaic, src_transform = merge(datasets, nodata=NODATA, dtype="float32")
            source = mosaic[0].astype("float32")
            source[source == NODATA] = np.nan
            src_crs = datasets[0].crs
    finally:
        for dataset in datasets:
            dataset.close()
    nodata_val = NODATA
    source = np.where(np.isfinite(source), source, nodata_val).astype("float32")
    out = np.full(grid.data.shape, nodata_val, dtype="float32")
    reproject(
        source,
        out,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=nodata_val,
        dst_transform=grid.transform,
        dst_crs=f"EPSG:{grid.epsg}",
        dst_nodata=nodata_val,
        resampling=Resampling.average if downsample else Resampling.bilinear,
    )
    out[out == nodata_val] = np.nan
    # Anything the lidar tile stored as an exact zero is a void, not sea level.
    out[out == 0.0] = np.nan
    return out


def feathered_composite(base: np.ndarray, overlay: np.ndarray, feather_px: int = 24) -> tuple[np.ndarray, dict]:
    """Overlay on base where the overlay is valid, blended across a feathered margin.

    The overlay is first shifted by the median (overlay - base) in the overlap, so two
    surveys on different vertical datums do not leave a step at the seam.
    """

    from scipy import ndimage

    valid = np.isfinite(overlay)
    stats = {"overlay_valid_fraction": float(valid.mean()), "datum_shift_m": 0.0}
    if not valid.any():
        return base, stats
    both = valid & np.isfinite(base)
    if both.sum() > 1000:
        shift = float(np.median(base[both] - overlay[both]))
        stats["datum_shift_m"] = shift
        overlay = overlay + shift
    # Weight 1 deep inside the overlay, ramping to 0 at its edge.
    distance = ndimage.distance_transform_edt(valid)
    weight = np.clip(distance / float(feather_px), 0.0, 1.0).astype("float32")
    weight[~valid] = 0.0
    weight[~np.isfinite(base)] = np.where(valid[~np.isfinite(base)], 1.0, 0.0)
    out = np.where(np.isfinite(base), base, 0.0) * (1.0 - weight) + np.where(valid, overlay, 0.0) * weight
    out[(~np.isfinite(base)) & (~valid)] = np.nan
    return out.astype("float32"), stats


def fill_holes(dem: np.ndarray) -> tuple[np.ndarray, int]:
    """Nearest-neighbour fill of NaN samples (rare seams and lidar voids)."""

    from scipy import ndimage

    holes = ~np.isfinite(dem)
    count = int(holes.sum())
    if count == 0:
        return dem, 0
    if holes.all():
        raise ValueError("no elevation data at all inside the footprint")
    indices = ndimage.distance_transform_edt(holes, return_distances=False, return_indices=True)
    filled = dem[tuple(indices)]
    return filled.astype("float32"), count


def despike(dem: np.ndarray, res: float, max_step_m: float) -> tuple[np.ndarray, int]:
    """Clamp isolated single-sample spikes (lidar noise returns) to their neighbourhood median."""

    from scipy import ndimage

    median = ndimage.median_filter(dem, size=3, mode="nearest")
    spikes = np.abs(dem - median) > max_step_m
    count = int(spikes.sum())
    if count:
        dem = np.where(spikes, median, dem).astype("float32")
    return dem, count


def slope_degrees(dem: np.ndarray, res: float) -> np.ndarray:
    gy, gx = np.gradient(dem.astype("float64"), res)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")


def hillshade(dem: np.ndarray, res: float, azimuth_deg: float = 315.0, altitude_deg: float = 45.0) -> np.ndarray:
    """0..1 Lambertian hillshade, north-up."""

    gy, gx = np.gradient(dem.astype("float64"), res)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = math.radians(azimuth_deg)
    alt = math.radians(altitude_deg)
    shade = math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0.0, 1.0).astype("float32")


def normal_map(dem: np.ndarray, res: float, strength: float = 1.0) -> np.ndarray:
    """Tangent-space-style RGB8 normal map of the terrain (north-up, +Y = north)."""

    gy, gx = np.gradient(dem.astype("float64"), res)
    nx = -gx * strength
    ny = gy * strength  # row index grows southward, so north is -row; flip to +Y north
    nz = np.ones_like(nx)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / length, ny / length, nz / length], axis=-1)
    return np.clip((rgb * 0.5 + 0.5) * 255.0, 0, 255).astype("uint8")


def ambient_occlusion(dem: np.ndarray, res: float, radius_px: int = 24) -> np.ndarray:
    """Cheap AO: how far below its smoothed surroundings a sample sits, 0..1 (1 = open)."""

    from scipy import ndimage

    smooth = ndimage.uniform_filter(dem.astype("float64"), size=2 * radius_px + 1, mode="nearest")
    depth = np.clip((smooth - dem) / (radius_px * res * 0.35), 0.0, 1.0)
    return (1.0 - 0.6 * depth).astype("float32")


def classify(dem: np.ndarray, res: float, terrain_spec: dict) -> tuple[np.ndarray, dict]:
    """Paint a u8 layer map from slope/elevation rules; first matching rule wins."""

    from scipy import ndimage

    materials = list(terrain_spec["materials"])
    rules = terrain_spec["classify"]["rules"]
    default = materials.index(terrain_spec["classify"]["default"])
    slope = ndimage.gaussian_filter(slope_degrees(dem, res), sigma=1.5)
    lo, hi = float(np.nanmin(dem)), float(np.nanmax(dem))
    frac = (dem - lo) / max(hi - lo, 1e-6)
    layer = np.full(dem.shape, default, dtype="uint8")
    assigned = np.zeros(dem.shape, dtype=bool)
    for rule in rules:
        mask = ~assigned
        if "min_slope" in rule:
            mask &= slope >= float(rule["min_slope"])
        if "max_slope" in rule:
            mask &= slope <= float(rule["max_slope"])
        if "min_elevation_frac" in rule:
            mask &= frac >= float(rule["min_elevation_frac"])
        if "max_elevation_frac" in rule:
            mask &= frac <= float(rule["max_elevation_frac"])
        layer[mask] = materials.index(rule["material"])
        assigned |= mask
    # Remove single-sample speckle so materials read as patches, not noise.
    layer = ndimage.median_filter(layer, size=5, mode="nearest").astype("uint8")
    counts = {name: float((layer == i).mean()) for i, name in enumerate(materials)}
    return layer, counts


@dataclass
class Encoded:
    heights_u16_south_up: np.ndarray  # BeamNG order: row 0 = south
    heights_u16_north_up: np.ndarray  # image order for the exported PNG
    layer_u8_south_up: np.ndarray
    layer_u8_north_up: np.ndarray
    min_elevation_m: float
    max_elevation_m: float
    max_height_m: float


def encode(dem: np.ndarray, layer: np.ndarray) -> Encoded:
    """u16 heights relative to the lowest sample, with maxHeight sized to the real range.

    maxHeight is the smallest whole number of metres that holds the range plus a 1 %
    margin, so the 16-bit ladder spends its precision on the terrain that exists
    rather than on the 2048 m default (0.4 cm steps on the crater, 1.9 cm on the pass).
    """

    lo = float(np.min(dem))
    hi = float(np.max(dem))
    span = hi - lo
    max_height = float(math.ceil(span * 1.01 + 1.0))
    scaled = np.round((dem - lo) * (65536.0 / max_height))
    heights = np.clip(scaled, 0, 65535).astype("<u2")
    return Encoded(
        heights_u16_south_up=np.ascontiguousarray(heights[::-1, :]),
        heights_u16_north_up=np.ascontiguousarray(heights),
        layer_u8_south_up=np.ascontiguousarray(layer[::-1, :]),
        layer_u8_north_up=np.ascontiguousarray(layer),
        min_elevation_m=lo,
        max_elevation_m=hi,
        max_height_m=max_height,
    )


def write_ter(path: Path, heights_south_up: np.ndarray, layer_south_up: np.ndarray, materials: list[str]) -> None:
    """BeamNG TerrainFile version 9: u8 version, u32 size, u16[] heights, u8[] layers,
    u32 count, then the material internal names."""

    size = heights_south_up.shape[0]
    assert heights_south_up.shape == (size, size) and layer_south_up.shape == (size, size)
    import struct

    with path.open("wb") as sink:
        sink.write(struct.pack("<B", 9))
        sink.write(struct.pack("<I", size))
        sink.write(heights_south_up.astype("<u2").tobytes(order="C"))
        sink.write(layer_south_up.astype("u1").tobytes(order="C"))
        sink.write(struct.pack("<I", len(materials)))
        for name in materials:
            encoded = name.encode("utf-8")
            sink.write(struct.pack("<B", len(encoded)))
            sink.write(encoded)


def write_png16(path: Path, array_u16: np.ndarray) -> None:
    from PIL import Image

    image = Image.fromarray(array_u16.astype("<u2"), mode="I;16")
    image.save(path, format="PNG", compress_level=6)


def write_png8(path: Path, array_u8: np.ndarray) -> None:
    from PIL import Image

    if array_u8.ndim == 2:
        Image.fromarray(array_u8.astype("uint8"), mode="L").save(path, format="PNG", compress_level=6)
    else:
        Image.fromarray(array_u8.astype("uint8"), mode="RGB").save(path, format="PNG", compress_level=6)
