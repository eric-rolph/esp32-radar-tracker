"""Mount St. Helens crater and Pumice Plain - authored constants for the generator and level.

The 1980 amphitheater: the horseshoe crater and its 2,000 ft headwall, the lava dome, and
the Pumice Plain's braided ash canyons running north toward Spirit Lake. A 4096-sample
terrain at 1.5 m per sample gives a 6144 m square that holds the whole amphitheater.
"""

MOD_ID = "ericrolph_mt_st_helens"
DISPLAY_NAME = "Mount St. Helens Pumice Plain"
ZIP_BASENAME = "mt_st_helens_ericrolph.zip"
AUTHOR = "ericrolph"

SITE = {
    "place": "Skamania County, Washington, USA",
    "center_lat": 46.222,
    "center_lon": -122.190,
    "epsg": 32610,
    "size_px": 4096,
    "square_size_m": 1.5,  # 6144 m footprint
}

SOURCES = {
    "elevation": [
        {"kind": "usgs_3dep", "resolution": 1.0,
         "citation": "WA_FEMAHQ_2018_D18 lidar via USGS 3DEP (post-eruption surface incl. the lava dome)"},
    ],
    "imagery": {"kind": "usgs_naip", "resolution": 1.5},
    "roads": {"kind": "osm_overpass"},
}

TERRAIN = {
    "materials": ["sh_pumice_plain", "sh_ash_gully", "sh_crater_wall", "sh_debris_slope", "sh_snow_ice"],
    "classify": {
        "rules": [
            {"min_elevation_frac": 0.86, "min_slope": 20.0, "material": "sh_snow_ice"},
            {"min_slope": 34.0, "material": "sh_crater_wall"},
            {"min_slope": 16.0, "material": "sh_debris_slope"},
            {"min_slope": 5.0, "material": "sh_ash_gully"},
        ],
        "default": "sh_pumice_plain",
    },
    "smooth_sigma_px": 0.0,
}

PALETTE = {
    "sh_pumice_plain": {"family": "gravel", "seed": 401, "size": 1024, "base": [0.55, 0.52, 0.48]},
    "sh_ash_gully": {"family": "volcanic_ash", "seed": 402, "size": 1024, "base": [0.40, 0.38, 0.36]},
    "sh_crater_wall": {"family": "rock_strata", "seed": 403, "size": 1024, "base": [0.42, 0.38, 0.35]},
    "sh_debris_slope": {"family": "scree", "seed": 404, "size": 1024, "base": [0.36, 0.34, 0.33]},
    "sh_snow_ice": {"family": "snow", "seed": 405, "size": 1024, "base": [0.88, 0.90, 0.93]},
}

ROADS = {
    "include": ["primary", "secondary", "tertiary", "unclassified", "residential", "service", "track"],
    "widths": {"primary": 8.0, "secondary": 7.0, "tertiary": 6.0, "unclassified": 5.0,
               "residential": 5.0, "service": 4.0, "track": 3.5},
    "material": {"name": "road_gravel", "family": "gravel", "seed": 900, "base": [0.60, 0.55, 0.47]},
}

SPAWNS = [
    {"name": "pumice_plain", "lat": 46.238, "lon": -122.190, "heading_deg": 180.0, "default": True},
    {"name": "crater_mouth", "lat": 46.215, "lon": -122.190, "heading_deg": 180.0},
    {"name": "toutle_hummocks", "lat": 46.245, "lon": -122.215, "heading_deg": 135.0},
]

SKY = {"time": 0.90, "utc_offset": "-7", "year": 2026, "month": 8, "day": 1}

BIOME = "Volcanic ash plain"
FEATURES = "1980 crater headwall, lava dome, braided ash canyons of the Pumice Plain"
SUITABLE_FOR = "Technical wash navigation, crawling over volcanic debris, big drops"
ROADS_TEXT = "No roads: hiking trails only; expect to drive the washes"

DESCRIPTION = (
    "Mount St. Helens' 1980 crater and the Pumice Plain, rebuilt from USGS 3DEP 1 m lidar. "
    "A 6 km square at 1.5 m per sample: the 600 m crater headwall, the lava dome, and the "
    "sheer-walled braided canyons cut through ash and pumice on the way down to Spirit Lake."
)
