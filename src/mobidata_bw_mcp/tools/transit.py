from datetime import date, datetime
from typing import Any

from ..clients import geocode, gtfs, wfs
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
        wfs.features(
            "MobiData-BW:transit_stations_with_served_routes", bbox=bbox, limit=1000
        ),
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
    """Get scheduled departures for a stop or station; dates near today may not be published yet."""
    bounded = limit_value(limit)
    service_date = date_value or (from_time.date() if from_time else date.today())
    params: dict[str, Any] = {
        "or": f"(stop_id.eq.{stop_or_station_id},station_id.eq.{stop_or_station_id})",
        "date": f"eq.{service_date.isoformat()}",
        "order": "t_departure",
        "limit": bounded,
    }
    if from_time:
        params["t_departure"] = f"gte.{from_time.isoformat()}"
    records = await gtfs.departures(params)
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
    return ResultEnvelope(
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