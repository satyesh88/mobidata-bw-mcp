import logging
import time
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

from ..clients import geocode, gtfs, wfs
from ..clients.http import SourceTimeout
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, geometry_location, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import limit_value


async def find_transit(
    location: LocationInput | dict[str, Any], radius_m: int = 500
) -> dict[str, Any]:
    """Find scheduled-transit stops and stations nearby; this is not realtime service data."""
    resolved = await geocode.resolve(location)
    bbox = bbox_around(resolved, radius_m)
    payloads = await __import__("asyncio").gather(
        wfs.features("MobiData-BW:transit_stops", bbox=bbox, limit=1000),
        wfs.features("MobiData-BW:transit_stations_with_served_routes", bbox=bbox, limit=1000),
    )
    items = []
    for item_type, payload in zip(("stop", "station"), payloads, strict=True):
        for feature in payload.get("features", []):
            props = feature["properties"]
            lat, lon = geometry_location(feature["geometry"])
            distance = haversine_m(resolved.lat, resolved.lon, lat, lon)
            if distance > radius_m:
                continue
            items.append(
                compact_dict(
                    {
                        "item_type": item_type,
                        "id": props.get("stop_id") or props.get("station_id"),
                        "name": props.get("stop_name") or props.get("station_name"),
                        "wheelchair_boarding": props.get("wheelchair_boarding"),
                        "routes": props.get("routes"),
                        "lat": lat,
                        "lon": lon,
                        "distance_m": round(distance),
                    }
                )
            )
    items.sort(key=lambda item: item["distance_m"])
    return ResultEnvelope(
        query={"location": resolved.model_dump(exclude_none=True), "radius_m": radius_m},
        count=len(items),
        items=items,
        source=source_info("transit-stops", settings.wfs_url, DATASET_LICENSES["gtfs"]),
        warnings=["Scheduled GTFS data only; no realtime disruption or delay information."],
    ).compact()


async def get_departures(
    stop_or_station_id: str,
    date_value: date | None = None,
    from_time: datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        return await _get_departures(stop_or_station_id, date_value, from_time, limit)
    except (TimeoutError, SourceTimeout):
        logging.getLogger(__name__).info(
            "departures error=source_timeout total_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        return {
            "error": "source_timeout", "partial": True,
            "message": "The timetable source didn’t respond.",
        }


async def _get_departures(
    stop_or_station_id: str,
    date_value: date | None = None,
    from_time: datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Get scheduled departures for a stop or station; dates near today may not be published yet."""
    bounded = min(limit_value(limit), 20)
    start = time.perf_counter()
    berlin = ZoneInfo("Europe/Berlin")
    if from_time is not None:
        from_time = (
            from_time.replace(tzinfo=berlin)
            if from_time.tzinfo is None
            else from_time.astimezone(berlin)
        )
    service_date = date_value or (from_time.date() if from_time else datetime.now(berlin).date())
    requested = datetime.combine(
        service_date, from_time.timetz() if from_time else clock_time(), tzinfo=berlin
    )
    ids = await gtfs.resolve_stop_ids(stop_or_station_id)
    lookup_ms = (time.perf_counter() - start) * 1000
    query_start = time.perf_counter()
    # Hour buckets retain exact windows separately: 09:55 must never reuse 09:00's
    # truncated rows, and callers with different limits must not poison one another.
    bucket_key = (tuple(ids), service_date.isoformat(), requested.hour)
    window_key = (requested.isoformat(), bounded)
    bucket = gtfs._departure_cache.get(bucket_key, {})
    cache_hit = window_key in bucket
    if cache_hit:
        records = bucket[window_key]
    elif not ids:
        records = []
    else:
        quoted = ",".join('"' + value.replace('"', "") + '"' for value in ids)
        params: dict[str, Any] = {
            "select": gtfs.COLUMNS,
            "stop_id": f"in.({quoted})",
            "_start": requested.isoformat(),
            "date": f"eq.{service_date.isoformat()}",
            "and": f"(t_departure.gte.{requested.isoformat()},"
            f"t_departure.lt.{(requested + timedelta(minutes=90)).isoformat()})",
            "order": "t_departure",
            "limit": bounded,
        }
        records = await gtfs.departures(params)
        bucket = {**bucket, window_key: records}
        if bucket_key not in gtfs._departure_cache:
            gtfs._departure_cache[bucket_key] = bucket
        else:
            gtfs._departure_cache[bucket_key][window_key] = records
    query_ms = (time.perf_counter() - query_start) * 1000
    formatting_start = time.perf_counter()
    items = [
        compact_dict(
            {
                "route": record.get("route_short_name"),
                "headsign": record.get("trip_headsign"),
                "departure": record.get("t_departure"),
                "scheduled_time": record.get("departure_time"),
                "stop_id": record.get("stop_id"),
                "stop_name": record.get("stop_name"),
                "station_name": record.get("station_name"),
                "wheelchair_accessible": record.get("wheelchair_accessible"),
            }
        )
        for record in records
    ]
    warnings = (
        ["No scheduled departures found; the requested date may not be published yet."]
        if not items
        else []
    )
    warnings.append("Times are scheduled, not realtime.")
    result = ResultEnvelope(
        query={
            "stop_or_station_id": stop_or_station_id,
            "date": service_date.isoformat(),
            "from_time": from_time.isoformat() if from_time else None,
            "limit": bounded,
        },
        count=len(items),
        items=items,
        source=source_info("gtfs-arrivals-departures", settings.gtfs_url, DATASET_LICENSES["gtfs"]),
        warnings=warnings,
    ).compact()

    logging.getLogger(__name__).info(
        "departures stop_lookup_ms=%.1f stop_id_count=%d postgrest_ms=%.1f "
        "formatting_ms=%.1f cache_hit=%s total_ms=%.1f",
        lookup_ms,
        len(ids),
        query_ms,
        (time.perf_counter() - formatting_start) * 1000,
        cache_hit,
        (time.perf_counter() - start) * 1000,
    )
    return result
