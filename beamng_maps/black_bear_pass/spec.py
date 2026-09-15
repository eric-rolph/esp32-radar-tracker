"""Black Bear Pass and Ingram Basin - authored constants for the generator and the level.

A 12,840 ft shelf road descending from the pass through the Steps and the switchbacks
above Bridal Veil Falls into Ingram Basin. All above tree line: tundra, talus and rock.
A 4096 m square at 1 m per sample from USGS 3DEP (San Luis / San Juan / Miguel 2020 lidar).
"""

MOD_ID = "ericrolph_black_bear_pass"
DISPLAY_NAME = "Black Bear Pass"
ZIP_BASENAME = "black_bear_pass_ericrolph.zip"
AUTHOR = "ericrolph"

SITE = {
    "place": "San Juan Mountains, San Miguel / Ouray County, Colorado, USA",
    "center_lat": 37.912,
    "center_lon": -107.762,
    "epsg": 32613,
    "size_px": 4096,
    "square_size_m": 1.0,
}

SOURCES = {
    "elevation": [
        {"kind": "usgs_3dep", "resolution": 1.0,
         "citation": "CO_SanLuisJuanMiguel_2020_D20 lidar via USGS 3DEP"},
    ],
    "imagery": {"kind": "usgs_naip", "resolution": 1.0},
    "roads": {"kind": "osm_overpass"},
}

TERRAIN = {
    "materials": ["bb_tundra", "bb_talus", "bb_cliff_rock", "bb_scree_slope"],
    "classify": {
        "rules": [
            {"min_slope": 45.0, "material": "bb_cliff_rock"},
            {"min_slope": 30.0, "material": "bb_scree_slope"},
            {"min_slope": 15.0, "material": "bb_talus"},
        ],
        "default": "bb_tundra",
    },
    "smooth_sigma_px": 0.0,
}

PALETTE = {
    "bb_tundra": {"family": "alpine_tundra", "seed": 501, "size": 1024, "base": [0.46, 0.46, 0.30]},
    "bb_talus": {"family": "scree", "seed": 502, "size": 1024, "base": [0.48, 0.44, 0.40]},
    "bb_cliff_rock": {"family": "rock_strata", "seed": 503, "size": 1024, "base": [0.40, 0.36, 0.33]},
    "bb_scree_slope": {"family": "shale", "seed": 504, "size": 1024, "base": [0.42, 0.40, 0.38]},
}

ROADS = {
    "include": ["primary", "secondary", "tertiary", "unclassified", "residential", "service", "track"],
    "widths": {"primary": 8.0, "secondary": 7.0, "tertiary": 6.0, "unclassified": 5.0,
               "residential": 5.0, "service": 4.0, "track": 3.2},
    "material": {"name": "road_gravel", "family": "gravel", "seed": 900, "base": [0.60, 0.55, 0.47]},
}

SPAWNS = [
    {"name": "pass_summit", "lat": 37.9006, "lon": -107.7481, "heading_deg": 300.0, "default": True},
    {"name": "the_steps", "lat": 37.9145, "lon": -107.7625, "heading_deg": 300.0},
    {"name": "bridal_veil_top", "lat": 37.9215, "lon": -107.7700, "heading_deg": 320.0},
]

SKY = {"time": 0.88, "utc_offset": "-6", "year": 2026, "month": 8, "day": 15}

BIOME = "Alpine tundra and talus"
FEATURES = "3,913 m pass, one-way shelf road, the Steps, switchbacks above Bridal Veil Falls"
SUITABLE_FOR = "Rock crawling, articulation and low-range gearing tests"
ROADS_TEXT = "Black Bear Pass Road (OSM), Bridal Veil and Imogene tracks"

DESCRIPTION = (
    "Black Bear Pass and Ingram Basin, Colorado, rebuilt from USGS 3DEP 1 m lidar. A 4 km "
    "square at 1 m per sample from the 3,913 m summit down the one-way shelf road, the "
    "Steps and the switchbacks above Bridal Veil Falls. Entirely above tree line."
)
