from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ckan_url: str = "https://mobidata-bw.de/api/3/action/"
    wfs_url: str = "https://api.mobidata-bw.de/geoserver/MobiData-BW/ows"
    parkapi_url: str = "https://api.mobidata-bw.de/park-api/api/public/v3/"
    gtfs_url: str = "https://api.mobidata-bw.de/gtfs/"
    gbfs_manifest_url: str = "https://api.mobidata-bw.de/sharing/gbfs/v3/manifest.json"
    roadworks_url: str = (
        "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json"
    )
    signs_url: str = "https://mobidata-bw.de/daten/portal/VZ-Daten/signs.geojson"
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    user_agent: str = (
        "mobidata-bw-mcp/0.1.0 (+https://github.com/satyesh88/mobidata-bw-mcp)"
    )
    timeout_seconds: float = 20.0
    max_concurrency: int = 4
    realtime_ttl: int = 60
    roadworks_ttl: int = 900
    capabilities_ttl: int = 86400
    signs_ttl: int = 86400
    geocode_ttl: int = 604800
    ckan_ttl: int = 3600
    bfrk_ttl: int = 86400
    default_limit: int = 20
    max_limit: int = 200


settings = Settings()

LAYER_GEOMETRY_FIELDS = {
    "MobiData-BW:roadworks": "geometry",
    "MobiData-BW:charge_points": "geometry",
    "MobiData-BW:park-api_car": "geometry",
    "MobiData-BW:park-api_car_lines": "geometry",
    "MobiData-BW:park-api_car_polygons": "geometry",
    "MobiData-BW:park-api_bicycle": "geometry",
    "MobiData-BW:sharing_stations": "geometry",
    "MobiData-BW:sharing_vehicles": "geometry",
    "MobiData-BW:transit_stops": "stop_loc",
    "MobiData-BW:transit_stations_with_served_routes": "centroid",
    "MobiData-BW:transit_shapes_with_routes": "shape",
    "MobiData-BW:radvis_cycle_network": "wkb_geometry",
    "MobiData-BW:bicycle_service_points": "geometry",
}

DATASET_LICENSES = {
    "wfs": "See individual MobiData BW dataset metadata",
    "parking": "Datenlizenz Deutschland - Namensnennung - Version 2.0",
    "roadworks": "Datenlizenz Deutschland - Namensnennung - Version 2.0",
    "signs": "Datenlizenz Deutschland - Namensnennung - Version 2.0",
    "gtfs": "CC BY 4.0",
    "bfrk": "Datenlizenz Deutschland Namensnennung 2.0",
}