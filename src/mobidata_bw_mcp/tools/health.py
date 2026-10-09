from collections import Counter
from typing import Any

from ..clients import geocode, parkapi, wfs
from ..config import DATASET_LICENSES, settings
from ..models import ResultEnvelope, source_info
from .common import freshness


async def _parking_health(bbox: Any | None) -> dict[str, Any]:
    params = (
        {
            "lat_min": bbox.min_lat,
            "lat_max": bbox.max_lat,
            "lon_min": bbox.min_lon,
            "lon_max": bbox.max_lon,
        }
        if bbox
        else {}
    )
    records = await parkapi.all_parking_sites(params)
    live = sum(
        freshness(
            record.get("realtime_data_updated_at"),
            live_available=bool(record.get("has_realtime_data")),
        )["is_live"]
        for record in records
    )
    return {
        "dataset": "parking",
        "count": len(records),
        "live_count": live,
        "status": "ok" if records else "no_data",
        "live_percent": round(live * 100 / len(records), 1) if records else None,
        "stale_or_static_count": len(records) - live,
        "top_regions": Counter(
            record.get("official_region_code") for record in records
        ).most_common(10),
    }


async def _wfs_health(layer: str, dataset: str, bbox: Any | None) -> dict[str, Any]:
    payload = await wfs.features(layer, bbox=bbox, limit=10_000)
    records = [feature.get("properties", {}) for feature in payload.get("features", [])]
    timestamp_field = "last_reported" if dataset == "sharing" else "status_last_updated"
    live = sum(
        freshness(
            record.get(timestamp_field),
            outdated=record.get("realtime_data_outdated"),
            live_available=record.get(timestamp_field) is not None,
        )["is_live"]
        for record in records
    )
    return {
        "dataset": dataset,
        "count": len(records),
        "live_count": live,
        "status": "ok" if records else "no_data",
        "live_percent": round(live * 100 / len(records), 1) if records else None,
        "stale_or_static_count": len(records) - live,
        "top_regions": Counter(
            record.get("official_region_code") or record.get("city") for record in records
        ).most_common(10),
    }


async def data_health(region: str | None = None, dataset: str = "all") -> dict[str, Any]:
    """Compute current live-data freshness for parking, charging, and sharing feeds."""
    if dataset not in {"parking", "charging", "sharing", "all"}:
        raise ValueError("dataset must be parking, charging, sharing, or all")
    resolved_region, region_bbox = await geocode.resolve_bbox(region) if region else (None, None)
    coroutines = []
    if dataset in {"parking", "all"}:
        coroutines.append(_parking_health(region_bbox))
    if dataset in {"charging", "all"}:
        coroutines.append(_wfs_health("MobiData-BW:charge_points", "charging", region_bbox))
    if dataset in {"sharing", "all"}:
        coroutines.append(
            _wfs_health("MobiData-BW:sharing_stations", "sharing", region_bbox)
        )
    items = list(await __import__("asyncio").gather(*coroutines))
    warnings = []
    for item in items:
        if item["status"] == "no_data":
            warnings.append(f"{item['dataset']}: no data found in the requested region")
        elif item["live_percent"] < 50:
            warnings.append(
                f"{item['dataset']}: only {item['live_percent']}% of records are current/live"
            )
    return ResultEnvelope(
        query={
            "region": region,
            "resolved_region": resolved_region.model_dump(exclude_none=True)
            if resolved_region
            else None,
            "bbox": region_bbox.model_dump() if region_bbox else None,
            "dataset": dataset,
        },
        count=len(items),
        items=items,
        source=source_info(
            "mobility-data-health",
            f"{settings.parkapi_url} + {settings.wfs_url}",
            f"{DATASET_LICENSES['parking']}; {DATASET_LICENSES['wfs']}",
        ),
        warnings=warnings,
    ).compact()