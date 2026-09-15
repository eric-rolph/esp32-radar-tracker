"""Barringer Meteor Crater - authored constants shared by the generator and the level.

A 1.2 km impact bowl 170 m deep, sitting in a 2048 m square at 0.5 m per sample so the
NCALM 0.25 m lidar survives as terrain: the upturned rim strata, the talus aprons inside
the bowl, and the low ejecta swells across the desert floor. Nothing man-made is inside
the level except the rim access road and the visitor-center car park.
"""

MOD_ID = "ericrolph_meteor_crater"
DISPLAY_NAME = "Barringer Meteor Crater"
ZIP_BASENAME = "meteor_crater_ericrolph.zip"
AUTHOR = "ericrolph"

SITE = {
    "place": "Coconino County, Arizona, USA",
    "center_lat": 35.0275,
    "center_lon": -111.0225,
    "epsg": 32612,  # WGS 84 / UTM zone 12N
    "size_px": 4096,  # heightmap edge in samples (power of two)
    "square_size_m": 0.5,  # metres per sample -> 2048 m footprint
}

SOURCES = {
    "elevation": [
        # Baseline everywhere: fills anything the lidar grid does not cover.
        {"kind": "usgs_3dep", "resolution": 1.0},
        # NCALM airborne lidar, 0.25 m grid (Palucis 2010, OpenTopography OTSDEM.112011.26912.3).
        {
            "kind": "ot_grid",
            "prefix": "AZ10_Palucis/AZ10_Palucis_hh/",
            "open_name": "hdr.adf",
            "name": "az10_palucis_hh",
            "citation": "Meteor Crater, AZ (2010). NCALM / M. Palucis. https://doi.org/10.5069/G9V40S4C",
            "license": "OpenTopography - freely available; cite the DOI",
        },
    ],
    "imagery": {"kind": "usgs_naip", "resolution": 0.5},
    "roads": {"kind": "osm_overpass"},
}

TERRAIN = {
    # index 0 is the default surface; the classifier below paints the others by slope.
    "materials": ["mc_desert_floor", "mc_ejecta_gravel", "mc_limestone_rim", "mc_talus"],
    "classify": {
        # slope in degrees -> material index; evaluated in order, first match wins
        "rules": [
            {"min_slope": 28.0, "material": "mc_limestone_rim"},
            {"min_slope": 14.0, "material": "mc_talus"},
            {"min_slope": 5.0, "material": "mc_ejecta_gravel"},
        ],
        "default": "mc_desert_floor",
    },
    "smooth_sigma_px": 0.0,
}

PALETTE = {
    "mc_desert_floor": {"family": "desert_floor", "seed": 101, "size": 1024, "base": [0.62, 0.53, 0.40]},
    "mc_ejecta_gravel": {"family": "gravel", "seed": 102, "size": 1024, "base": [0.56, 0.47, 0.36]},
    "mc_limestone_rim": {"family": "rock_strata", "seed": 103, "size": 1024, "base": [0.66, 0.58, 0.47]},
    "mc_talus": {"family": "scree", "seed": 104, "size": 1024, "base": [0.50, 0.42, 0.33]},
}

ROADS = {
    "include": ["primary", "secondary", "tertiary", "unclassified", "residential", "service", "track"],
    "widths": {"primary": 8.0, "secondary": 7.0, "tertiary": 6.0, "unclassified": 5.0,
               "residential": 5.0, "service": 4.0, "track": 3.5},
    "material": {"name": "road_gravel", "family": "gravel", "seed": 900, "base": [0.60, 0.55, 0.47]},
}

SPAWNS = [
    {"name": "north_rim_visitor_center", "lat": 35.0335, "lon": -111.0222, "heading_deg": 180.0, "default": True},
    {"name": "crater_floor", "lat": 35.0275, "lon": -111.0225, "heading_deg": 0.0},
    {"name": "south_rim", "lat": 35.0225, "lon": -111.0225, "heading_deg": 0.0},
]

SKY = {"time": 0.14, "utc_offset": "-7", "year": 2026, "month": 6, "day": 20}

BIOME = "Desert impact crater"
FEATURES = "1.2 km impact bowl, rim strata, talus, ejecta flats"
SUITABLE_FOR = "High-speed perimeter runs, scree hill climbs, rim drops"
ROADS_TEXT = "One gravel access road and the visitor-center loop; the rest is open desert"

DESCRIPTION = (
    "Barringer Meteor Crater, Arizona, rebuilt from 0.25 m NCALM airborne lidar and "
    "USGS 3DEP. A 1.2 km, 170 m deep impact bowl in a 2 km square at 0.5 m per terrain "
    "sample: rim strata, interior talus aprons and the ejecta ripples of the desert floor "
    "are all measured, not sculpted."
)
