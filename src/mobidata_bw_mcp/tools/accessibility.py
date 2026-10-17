import asyncio
import re
from datetime import datetime
from typing import Any

from ..clients import bfrk, geocode, parkapi
from ..config import DATASET_LICENSES, settings
from ..geo import compact_dict, haversine_m
from ..models import Location, LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime, limit_value

BFRK_CAVEATS = [
    "BFRK accessibility surveys were collected in different years and may be "
    "outdated; check the survey date for each item.",
    "BFRK object coordinates are deliberately offset by approximately 1.5 to 4 metres.",
    "Elevator details describe surveyed infrastructure, not live operational status.",
]


def _number(value: Any) -> float | None:
    if value in (None, "", "unbekannt"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _coordinates(row: dict[str, str], *, disabled: bool = False) -> tuple[float, float] | None:
    latitude = _number(
        row.get("Behindertenparkplaetze_Latitude") if disabled else row.get("Latitude")
    )
    longitude = _number(
        row.get("Behindertenparkplaetze_Longitude") if disabled else row.get("Longitude")
    )
    if latitude is None or longitude is None:
        latitude = _number(row.get("Latitude"))
        longitude = _number(row.get("Longitude"))
    return (latitude, longitude) if latitude is not None and longitude is not None else None


def _survey_year(row: dict[str, str]) -> int | None:
    try:
        return datetime.strptime(row.get("Erfassungsdatum", ""), "%d.%m.%Y").year
    except ValueError:
        return None


def _photo_links(joined: dict[str, Any]) -> list[str]:
    rows = [joined["Haltestelle"]]
    rows.extend(row for key, values in joined.items() if key != "Haltestelle" for row in values)
    return list(
        dict.fromkeys(
            value
            for row in rows
            for key, value in row.items()
            if key.casefold().endswith("foto") and value.startswith("http")
        )
    )[:20]


async def _bfrk_parking(resolved: Location, radius_m: int) -> list[dict[str, Any]]:
    tables = await asyncio.gather(
        bfrk.table("SPNV", "BFRK_Parkplatz.csv"),
        bfrk.table("OEPNV", "BFRK_Parkplatz.csv"),
    )
    items = []
    for mode, rows in zip(("SPNV", "OEPNV"), tables, strict=True):
        for row in rows:
            capacity = _integer(row.get("Stellplatzanzahl_Behinderte"))
            if not (capacity and capacity > 0) and row.get("Art") != "Behindertenparkplatz":
                continue
            coordinates = _coordinates(row, disabled=True)
            if coordinates is None:
                continue
            distance = haversine_m(resolved.lat, resolved.lon, *coordinates)
            if distance > radius_m:
                continue
            year = _survey_year(row)
            items.append(
                compact_dict(
                    {
                        "id": row.get("ID"),
                        "name": row.get("HST_Name") or row.get("Art"),
                        "type": row.get("Art"),
                        "capacity_disabled": capacity,
                        "lat": coordinates[0],
                        "lon": coordinates[1],
                        "distance_m": round(distance),
                        "source_label": f"BFRK survey {year}" if year else "BFRK survey",
                        "survey_date": row.get("Erfassungsdatum"),
                        "survey_year": year,
                        "network": mode,
                    }
                )
            )
    return items


async def find_accessible_parking(
    location: LocationInput | dict[str, Any],
    radius_m: int = 1000,
    limit: int = 20,
) -> dict[str, Any]:
    """Find disabled parking from live ParkAPI records and BFRK accessibility surveys."""
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    bounded_limit = limit_value(limit)
    resolved = await geocode.resolve(location)
    parkapi_result, survey_items = await asyncio.gather(
        parkapi.nearest_parking_sites(
            {"lat": resolved.lat, "lon": resolved.lon, "purpose": "CAR"}, radius_m
        ),
        _bfrk_parking(resolved, radius_m),
    )
    records, searched_radius = parkapi_result
    live_items = []
    for record in records:
        if not (record.get("capacity_disabled") or 0) > 0:
            continue
        live_items.append(
            compact_dict(
                {
                    "id": record.get("id"),
                    "name": record.get("name"),
                    "address": record.get("address"),
                    "capacity_disabled": record.get("capacity_disabled"),
                    "realtime_free_capacity_disabled": record.get(
                        "realtime_free_capacity_disabled"
                    ),
                    "lat": record.get("lat"),
                    "lon": record.get("lon"),
                    "distance_m": round(
                        haversine_m(
                            resolved.lat,
                            resolved.lon,
                            record["lat"],
                            record["lon"],
                        )
                    ),
                    "source_label": "live",
                    **freshness(
                        record.get("realtime_data_updated_at"),
                        live_available=(
                            record.get("realtime_free_capacity_disabled") is not None
                        ),
                    ),
                }
            )
        )
    items = sorted(live_items + survey_items, key=lambda item: item["distance_m"])
    truncated = len(items) > bounded_limit
    warnings = list(BFRK_CAVEATS)
    if searched_radius < radius_m:
        warnings.append(
            f"Dense area: live ParkAPI sites were searched only within the nearest "
            f"{searched_radius} m of the requested {radius_m} m."
        )
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True),
            "radius_m": radius_m,
            "limit": bounded_limit,
        },
        count=min(len(items), bounded_limit),
        truncated=truncated,
        items=items[:bounded_limit],
        source=source_info(
            "ParkAPI and BFRK accessible parking",
            f"{settings.parkapi_url}parking-sites + {settings.ckan_url}",
            f"{DATASET_LICENSES['parking']}; {DATASET_LICENSES['bfrk']}",
        ),
        data_timestamp=latest_datetime(
            [record.get("realtime_data_updated_at") for record in records]
        ),
        warnings=warnings,
    ).compact()


async def _all_stops() -> list[tuple[str, dict[str, str]]]:
    tables = await asyncio.gather(
        bfrk.table("SPNV", "BFRK_Haltestelle.csv"),
        bfrk.table("OEPNV", "BFRK_Haltestelle.csv"),
    )
    return [
        (mode, row)
        for mode, rows in zip(("SPNV", "OEPNV"), tables, strict=True)
        for row in rows
        if _coordinates(row) is not None
    ]


def _normalized_stop_text(value: str) -> str:
    normalized = re.sub(r"\bhbf\b", "hauptbahnhof", value.casefold())
    return " ".join(re.findall(r"[a-z0-9äöüß]+", normalized))


def _stop_search_text(row: dict[str, str]) -> str:
    return _normalized_stop_text(
        " ".join(
            filter(
                None,
                (row.get("HST_Name"), row.get("Gemeinde"), row.get("Ortsteil")),
            )
        )
    )


async def _select_stop(
    stop_or_location: LocationInput | dict[str, Any],
) -> tuple[str, dict[str, str], float | None]:
    stops = await _all_stops()
    if isinstance(stop_or_location, str):
        query = _normalized_stop_text(stop_or_location)
        query_tokens = set(query.split())
        matches = [
            item
            for item in stops
            if query_tokens <= set(_stop_search_text(item[1]).split())
        ]
        if matches:
            station_query = bool({"hauptbahnhof", "bahnhof"} & query_tokens)
            mode, row = min(
                matches,
                key=lambda item: (
                    0 if station_query and item[0] == "SPNV" else 1,
                    0 if _normalized_stop_text(item[1].get("HST_Name", "")) == query else 1,
                    len(set(_stop_search_text(item[1]).split()) - query_tokens),
                ),
            )
            return mode, row, None
    resolved = await geocode.resolve(stop_or_location)
    mode, row = min(
        stops,
        key=lambda item: haversine_m(resolved.lat, resolved.lon, *_coordinates(item[1])),
    )
    coordinates = _coordinates(row)
    return mode, row, haversine_m(resolved.lat, resolved.lon, *coordinates)


def _platform_identifiers(platform: dict[str, str]) -> set[str]:
    name = platform.get("STEIG_Name", "")
    identifiers = set(re.findall(r"\d+", name))
    if identifiers:
        return identifiers
    parts = platform.get("ID", "").split(":")
    return {parts[-1]} if parts and parts[-1].isdigit() else set()


def _connection_identifiers(row: dict[str, str]) -> set[str]:
    identifiers = set()
    connection = row.get("Verbindungsfunktion", "")
    for match in re.finditer(
        r"(?:gl(?:eis)?|bstg|bahnsteig)\s*(\d+(?:\s*/\s*\d+)*)",
        connection,
        re.IGNORECASE,
    ):
        identifiers.update(re.findall(r"\d+", match.group(1)))
    return identifiers


def _platform_access(joined: dict[str, Any]) -> list[dict[str, Any]]:
    accessible_connections = joined["Aufzug"] + joined["Rampe"]
    results = []
    for platform in joined["Haltesteig"]:
        identifiers = _platform_identifiers(platform)
        accessible = bool(
            identifiers
            and any(
                identifiers & _connection_identifiers(connection)
                for connection in accessible_connections
            )
        )
        stairs_only = bool(
            identifiers
            and any(
                identifiers & _connection_identifiers(connection)
                for connection in joined["Treppe"]
            )
        )
        status = "yes" if accessible else "no" if stairs_only else "unknown"
        results.append(
            {
                "platform": platform.get("STEIG_Name") or platform.get("ID"),
                "platform_id": platform.get("ID"),
                "step_free": status,
            }
        )
    return results


def _step_free_summary(platform_access: list[dict[str, Any]]) -> tuple[str, str]:
    statuses = [item["step_free"] for item in platform_access]
    if statuses and all(status == "yes" for status in statuses):
        return "yes", "Every surveyed platform has matching elevator or ramp access."
    if any(status == "no" for status in statuses):
        return "no", "At least one surveyed platform has only matching stair access."
    return "unknown", "Not every surveyed platform has conclusive access-path evidence."


async def stop_accessibility(
    stop_or_location: LocationInput | dict[str, Any],
) -> dict[str, Any]:
    """Summarize surveyed accessibility for a named or nearby Baden-Württemberg stop."""
    mode, stop, distance = await _select_stop(stop_or_location)
    stop_id = stop.get("HST_DHID") or stop["ID"]
    joined = await bfrk.joined_stop(mode, stop_id)
    platforms = joined["Haltesteig"]
    platform_access = _platform_access(joined)
    step_free, step_free_basis = _step_free_summary(platform_access)
    dates = [
        row.get("Erfassungsdatum")
        for value in joined.values()
        for row in ([value] if isinstance(value, dict) else value)
    ]
    years = sorted({year for row in [stop, *platforms] if (year := _survey_year(row))})
    coordinates = _coordinates(stop)
    item = compact_dict(
        {
            "id": stop_id,
            "name": stop.get("HST_Name"),
            "municipality": stop.get("Gemeinde"),
            "network": mode,
            "lat": coordinates[0] if coordinates else None,
            "lon": coordinates[1] if coordinates else None,
            "distance_m": round(distance) if distance is not None else None,
            "step_free": step_free,
            "step_free_basis": step_free_basis,
            "platform_access": platform_access,
            "platform_or_curb_heights_cm": sorted(
                {
                    value
                    for row in platforms
                    if (value := _number(row.get("Steighoehe_cm"))) is not None
                }
            ),
            "tactile_guidance": [
                compact_dict(
                    {
                        "platform": row.get("STEIG_Name") or row.get("ID"),
                        "boarding_area": row.get("Bodind_Einstiegsbereich"),
                        "guidance_strip": row.get("Bodind_Leitstreifen"),
                        "attention_field": row.get("Bodind_Auffindestreifen"),
                    }
                )
                for row in platforms
            ],
            "elevators": [
                compact_dict(
                    {
                        "id": row.get("ID"),
                        "door_width_cm": _number(row.get("Tuerweite_cm")),
                        "cabin_width_cm": _number(row.get("Kabinenbreite_cm")),
                        "cabin_length_cm": _number(row.get("Kabinenlaenge_cm")),
                        "connection": row.get("Verbindungsfunktion"),
                        "db_fasta_id": row.get("DB-FaSta-ID"),
                    }
                )
                for row in joined["Aufzug"]
            ],
            "ramps": [
                compact_dict(
                    {
                        "id": row.get("ID"),
                        "slope_percent": _number(row.get("Laengsneigung_prozent")),
                        "width_cm": _number(row.get("Breite_cm")),
                        "connection": row.get("Verbindungsfunktion"),
                    }
                )
                for row in joined["Rampe"]
            ],
            "wheelchair_toilets": [
                compact_dict(
                    {
                        "description": (
                            "accessible toilet (Euroschlüssel needed)"
                            if row.get("SchluesselEurokey") == "ja"
                            else "toilet"
                        ),
                        "wheelchair_accessible": (
                            "yes"
                            if row.get("SchluesselEurokey") == "ja"
                            else row.get("rollstuhltauglichAlle")
                            or row.get("rollstuhltauglich")
                        ),
                        "euro_key_needed": row.get("SchluesselEurokey") == "ja",
                        "opening_hours": row.get("Oeffnungszeiten"),
                        "source_fields": {
                            "rollstuhltauglich": row.get("rollstuhltauglich"),
                            "rollstuhltauglichAlle": row.get(
                                "rollstuhltauglichAlle"
                            ),
                            "SchluesselEurokey": row.get("SchluesselEurokey"),
                        },
                    }
                )
                for row in joined["Toilette"]
            ],
            "disabled_parking_spaces": sum(
                _integer(row.get("Stellplatzanzahl_Behinderte")) or 0
                for row in joined["Parkplatz"]
            ),
            "stairs_count": len(joined["Treppe"]),
            "bottlenecks": [
                compact_dict(
                    {
                        "width_cm": _number(row.get("Durchgangsbreite_cm")),
                        "movement_area_cm": _number(row.get("Bewegungsflaeche_cm")),
                    }
                )
                for row in joined["Engstelle"]
            ],
            "survey_years": years,
            "photo_links": _photo_links(joined),
        }
    )
    return ResultEnvelope(
        query={"stop_or_location": stop_or_location},
        count=1,
        items=[item],
        source=source_info(
            f"BFRK accessibility survey ({mode})",
            settings.ckan_url,
            DATASET_LICENSES["bfrk"],
        ),
        warnings=[*BFRK_CAVEATS, f"Survey dates present: {', '.join(filter(None, dates))}"],
    ).compact()