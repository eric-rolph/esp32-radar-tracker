"""Deterministic, tileable PBR texture sets for terrain materials.

The giant props pack seeds every material by name; this does the same by ``seed`` so
a rebuild on any machine writes pixel-identical maps. Everything is periodic gradient
noise composed in numpy: no external assets, no licences to carry.

Each family writes five maps at ``size`` px, named the way BeamNG's v1.5 terrain
materials expect them: ``<name>_b.png`` (base colour, sRGB), ``<name>_nm.png``
(tangent normal), ``<name>_r.png`` (roughness), ``<name>_h.png`` (height) and
``<name>_ao.png`` (ambient occlusion).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

FAMILIES = {
    # name: (octaves, base frequency (tiles per texture), roughness, height gain, feature)
    "desert_floor": {"freq": 6, "octaves": 5, "rough": 0.86, "gain": 0.55, "feature": "pebbles"},
    "gravel": {"freq": 10, "octaves": 5, "rough": 0.82, "gain": 0.9, "feature": "pebbles"},
    "rock_strata": {"freq": 3, "octaves": 6, "rough": 0.72, "gain": 1.0, "feature": "strata"},
    "scree": {"freq": 12, "octaves": 5, "rough": 0.78, "gain": 1.0, "feature": "blocks"},
    "dry_grass": {"freq": 8, "octaves": 5, "rough": 0.90, "gain": 0.5, "feature": "tufts"},
    "clay_pan": {"freq": 4, "octaves": 4, "rough": 0.70, "gain": 0.35, "feature": "cracks"},
    "shale": {"freq": 7, "octaves": 6, "rough": 0.76, "gain": 0.8, "feature": "rills"},
    "volcanic_ash": {"freq": 5, "octaves": 5, "rough": 0.92, "gain": 0.45, "feature": "pebbles"},
    "snow": {"freq": 3, "octaves": 4, "rough": 0.35, "gain": 0.3, "feature": "none"},
    "alpine_tundra": {"freq": 9, "octaves": 5, "rough": 0.88, "gain": 0.6, "feature": "tufts"},
    "macro_clumpy": {"freq": 4, "octaves": 4, "rough": 0.80, "gain": 0.4, "feature": "none"},
}


def _tileable_noise(size: int, period: int, rng: np.random.Generator) -> np.ndarray:
    """Periodic gradient (Perlin-style) noise, ``period`` lattice cells across the tile."""

    period = max(1, int(period))
    angles = rng.uniform(0.0, 2.0 * np.pi, size=(period, period))
    gx = np.cos(angles)
    gy = np.sin(angles)
    coords = np.arange(size, dtype="float64") * period / size
    xi = np.floor(coords).astype(int) % period
    xf = coords - np.floor(coords)
    yi, yf = xi, xf
    xi1 = (xi + 1) % period
    yi1 = (yi + 1) % period

    def fade(t):
        return t * t * t * (t * (t * 6 - 15) + 10)

    u = fade(xf)[None, :]
    v = fade(yf)[:, None]
    X, Y = np.meshgrid(xf, yf)
    n00 = gx[yi[:, None], xi[None, :]] * X + gy[yi[:, None], xi[None, :]] * Y
    n10 = gx[yi[:, None], xi1[None, :]] * (X - 1) + gy[yi[:, None], xi1[None, :]] * Y
    n01 = gx[yi1[:, None], xi[None, :]] * X + gy[yi1[:, None], xi[None, :]] * (Y - 1)
    n11 = gx[yi1[:, None], xi1[None, :]] * (X - 1) + gy[yi1[:, None], xi1[None, :]] * (Y - 1)
    nx0 = n00 * (1 - u) + n10 * u
    nx1 = n01 * (1 - u) + n11 * u
    return (nx0 * (1 - v) + nx1 * v) * 1.4142


def fbm(size: int, base_period: int, octaves: int, rng: np.random.Generator, persistence: float = 0.5) -> np.ndarray:
    total = np.zeros((size, size))
    amplitude = 1.0
    norm = 0.0
    for octave in range(octaves):
        total += amplitude * _tileable_noise(size, base_period * (2**octave), rng)
        norm += amplitude
        amplitude *= persistence
    return total / norm


def _feature(kind: str, size: int, rng: np.random.Generator) -> np.ndarray:
    """Family-specific height detail in -1..1, tileable."""

    if kind == "pebbles":
        cells = fbm(size, 24, 3, rng)
        return np.clip(np.abs(cells) * 2.2 - 0.4, -1, 1)
    if kind == "blocks":
        a = fbm(size, 10, 2, rng)
        b = fbm(size, 14, 2, rng)
        return np.sign(a) * np.minimum(np.abs(a) * 3.0, 1.0) * 0.6 + b * 0.4
    if kind == "strata":
        y = np.linspace(0, 1, size, endpoint=False)[:, None]
        warp = fbm(size, 2, 3, rng) * 0.08
        bands = np.sin(2 * np.pi * (y * 14 + warp)) * 0.5
        return bands + fbm(size, 16, 3, rng) * 0.3
    if kind == "tufts":
        t = fbm(size, 40, 2, rng)
        return np.where(t > 0.25, 1.0, -0.3) * 0.6 + fbm(size, 12, 3, rng) * 0.4
    if kind == "cracks":
        a = np.abs(fbm(size, 5, 2, rng))
        cracks = np.where(a < 0.035, -1.0, 0.2)
        return cracks + fbm(size, 20, 2, rng) * 0.15
    if kind == "rills":
        x = np.linspace(0, 1, size, endpoint=False)[None, :]
        warp = fbm(size, 3, 3, rng) * 0.05
        ridges = np.abs(np.sin(2 * np.pi * (x * 22 + warp))) * 2 - 1
        return ridges * 0.6 + fbm(size, 18, 3, rng) * 0.4
    return fbm(size, 6, 4, rng)


def _srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1 / 2.4) - 0.055)


def build_set(out_dir: Path, name: str, family: str, seed: int, size: int, base_rgb) -> dict[str, Path]:
    """Write the five maps for one material and return their paths keyed by suffix."""

    from PIL import Image

    params = FAMILIES[family]
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    low = fbm(size, params["freq"], params["octaves"], rng)
    detail = _feature(params["feature"], size, rng)
    height = np.clip(0.5 + 0.16 * low + 0.34 * params["gain"] * detail, 0.0, 1.0)

    # Colour: the authored base tinted by the height field and a slow hue drift.
    base = np.asarray(base_rgb, dtype="float64")
    drift = fbm(size, 2, 2, rng)
    shade = 0.80 + 0.55 * (height - 0.5) + 0.10 * drift
    warm = np.stack([1.0 + 0.06 * drift, np.ones_like(drift), 1.0 - 0.06 * drift], axis=-1)
    colour = np.clip(base[None, None, :] * shade[..., None] * warm, 0.0, 1.0)
    colour_u8 = (_srgb(colour) * 255.0).round().astype("uint8")

    # Normal from the height field (tangent space, +Y up in texture space).
    scale = 6.0 * params["gain"]
    gy, gx = np.gradient(height)
    nx = -gx * scale * size / 256.0
    ny = gy * scale * size / 256.0
    nz = np.ones_like(nx)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack([nx / length, ny / length, nz / length], axis=-1)
    normal_u8 = np.clip((normal * 0.5 + 0.5) * 255.0, 0, 255).astype("uint8")

    rough = np.clip(params["rough"] + 0.10 * (0.5 - height) + 0.05 * drift, 0.05, 1.0)
    rough_u8 = (rough * 255.0).round().astype("uint8")
    height_u8 = (height * 255.0).round().astype("uint8")
    ao = np.clip(1.0 - 0.5 * (0.5 - height).clip(0, None) * 2.0, 0.3, 1.0)
    ao_u8 = (ao * 255.0).round().astype("uint8")

    paths = {}
    for suffix, array, mode in (
        ("b", colour_u8, "RGB"),
        ("nm", normal_u8, "RGB"),
        ("r", rough_u8, "L"),
        ("h", height_u8, "L"),
        ("ao", ao_u8, "L"),
    ):
        path = out_dir / f"{name}_{suffix}.png"
        Image.fromarray(array, mode=mode).save(path, format="PNG", compress_level=6)
        paths[suffix] = path
    return paths
