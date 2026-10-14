from collections import Counter
from statistics import median
from typing import Any

from ..clients import geocode, parkapi, wfs
from ..config import DATASET_LICENSES, settings
from ..models import ResultEnvelope, source_info
from .common import parse_timestamp

FRESHNESS_THRESHOLD_MINUTES = 30


def _accessibility_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    site_count = len(records)
    capacity_count = sum(record.get("capacity_disabled") is not None for record in records)
    live_free_count = sum(
        record.get("realtime_free_capacity_disabled") is not None for record in records
    )
    return {
        "site_count": site_count,
        "with_disabled_capacity_count": capacity_count,
        "with_disabled_capacity_percent": (
            round(capacity_count * 100 / site_count, 1) if site_count else None
        ),
        "with_live_disabled_free_count": live_free_count,
        "with_live_disabled_free_percent": (
            round(live_free_count * 100 / site_count, 1) if site_count else None
        ),
        "percent_basis": "matching records / all parking sites after scope filtering",
    }


def _classify_records(
    records: list[dict[str, Any]], timestamp_field: str
) -> dict[str, Any]:
    from datetime import UTC, datetime

    fresh_count = 0
    stale_sites = []
    no_live_feed_count = 0
    live_ages: list[tuple[float, dict[str, Any], str]] = []
    for record in records:
        timestamp = record.get(timestamp_field)
        parsed = parse_timestamp(timestamp)
        if not timestamp:
            no_live_feed_count += 1
            continue
        age_minutes = (
            max(
                0.0,
                (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() / 60,
            )
            if parsed
            else None
        )
        if age_minutes is not None:
            live_ages.append((age_minutes, record, timestamp))
        is_stale = (
            parsed is None
            or age_minutes > FRESHNESS_THRESHOLD_MINUTES
            or record.get("realtime_data_outdated") is True
        )
        if is_stale:
            stale_sites.append(
                {
                    "name": record.get("name")
                    or record.get("feed_id")
                    or record.get("id")
                    or "Unnamed record",
                    "last_updated_at": timestamp,
                    "age_minutes": round(age_minutes, 1)
                    if age_minutes is not None
                    else None,
                }
            )
        else:
            fresh_count += 1
    live_capable_count = fresh_count + len(stale_sites)
    oldest_site = None
    if live_ages:
        oldest_age, oldest_record, oldest_timestamp = max(
            live_ages, key=lambda item: item[0]
        )
        oldest_site = {
            "name": oldest_record.get("name")
            or oldest_record.get("feed_id")
            or oldest_record.get("id")
            or "Unnamed record",
            "last_updated_at": oldest_timestamp,
            "age_minutes": round(oldest_age, 1),
        }
    return {
        "groups": {
            "live_and_fresh": fresh_count,
            "live_capable_but_stale": len(stale_sites),
            "no_live_feed": no_live_feed_count,
        },
        "live_capable_count": live_capable_count,
        "live_percent": round(fresh_count * 100 / live_capable_count, 1)
        if live_capable_count
        else None,
        "live_percent_basis": (
            "live_and_fresh / (live_and_fresh + live_capable_but_stale)"
        ),
        "stale_sites": stale_sites,
        "freshness_threshold_minutes": FRESHNESS_THRESHOLD_MINUTES,
        "median_age_min": round(median(age for age, _, _ in live_ages), 1)
        if live_ages
        else None,
        "max_age_min": round(max(age for age, _, _ in live_ages), 1)
        if live_ages
        else None,
        "oldest_site": oldest_site,
    }


async def _parking_health(
    bbox: Any | None,
    official_region_code: str | None,
    area_label: str | None,
    parking_scope: str,
) -> dict[str, Any]:
    if official_region_code:
        params = {"official_region_code": official_region_code}
        area_used = {
            "method": "official_region_code",
            "official_region_code": official_region_code,
            "label": area_label,
        }
    elif bbox:
        params = {
            "lat_min": bbox.min_lat,
            "lat_max": bbox.max_lat,
            "lon_min": bbox.min_lon,
            "lon_max": bbox.max_lon,
        }
        area_used = {"method": "bounding_box", "bbox": bbox.model_dump()}
    else:
        params = {}
        area_used = {"method": "all_baden_wuerttemberg"}
    records = await parkapi.all_parking_sites(params)
    on_street_count = sum(record.get("type") == "ON_STREET" for record in records)
    off_street_count = len(records) - on_street_count
    if parking_scope == "off_street":
        records = [record for record in records if record.get("type") != "ON_STREET"]
    elif parking_scope == "on_street":
        records = [record for record in records if record.get("type") == "ON_STREET"]
    return {
        "dataset": "parking",
        "count": len(records),
        "status": "ok" if records else "no_data",
        "parking_scope": parking_scope,
        "parking_type_counts_before_scope_filter": {
            "off_street": off_street_count,
            "on_street": on_street_count,
        },
        "area_used": area_used,
        "accessibility_coverage": _accessibility_coverage(records),
        **_classify_records(records, "realtime_data_updated_at"),
        "top_regions": Counter(
            record.get("official_region_code") for record in records
        ).most_common(10),
    }


async def _wfs_health(
    layer: str,
    dataset: str,
    bbox: Any | None,
    official_region_code: str | None,
    area_label: str | None,
) -> dict[str, Any]:
    use_region_code = bool(
        official_region_code and official_region_code.isdigit()
    )
    payload = await wfs.features(
        layer,
        bbox=None if use_region_code else bbox,
        cql_filter=(
            f"official_region_code = '{official_region_code}'"
            if use_region_code
            else None
        ),
        limit=10_000,
    )
    records = [feature.get("properties", {}) for feature in payload.get("features", [])]
    timestamp_field = "last_reported" if dataset == "sharing" else "status_last_updated"
    return {
        "dataset": dataset,
        "count": len(records),
        "status": "ok" if records else "no_data",
        "area_used": {
            "method": (
                "official_region_code"
                if use_region_code
                else "bounding_box"
                if bbox
                else "all_baden_wuerttemberg"
            ),
            **(
                {
                    "official_region_code": official_region_code,
                    "label": area_label,
                }
                if use_region_code
                else {"bbox": bbox.model_dump()}
                if bbox
                else {}
            ),
        },
        **_classify_records(records, timestamp_field),
        "top_regions": Counter(
            record.get("official_region_code") or record.get("city") for record in records
        ).most_common(10),
    }


async def data_health(
    region: str | None = None,
    dataset: str = "all",
    parking_scope: str = "off_street",
) -> dict[str, Any]:
    """Audit fresh, stale, and no-live-feed records; parking defaults to off-street."""
    if dataset not in {"parking", "charging", "sharing", "all"}:
        raise ValueError("dataset must be parking, charging, sharing, or all")
    if parking_scope not in {"off_street", "on_street", "all"}:
        raise ValueError("parking_scope must be off_street, on_street, or all")
    resolved_region, region_bbox, official_region_code = (
        await geocode.resolve_region(region) if region else (None, None, None)
    )
    coroutines = []
    if dataset in {"parking", "all"}:
        coroutines.append(
            _parking_health(
                region_bbox,
                official_region_code,
                resolved_region.label if resolved_region else None,
                parking_scope,
            )
        )
    if dataset in {"charging", "all"}:
        coroutines.append(
            _wfs_health(
                "MobiData-BW:charge_points",
                "charging",
                region_bbox,
                official_region_code,
                resolved_region.label if resolved_region else None,
            )
        )
    if dataset in {"sharing", "all"}:
        coroutines.append(
            _wfs_health(
                "MobiData-BW:sharing_stations",
                "sharing",
                region_bbox,
                official_region_code,
                resolved_region.label if resolved_region else None,
            )
        )
    items = list(await __import__("asyncio").gather(*coroutines))
    warnings = []
    for item in items:
        if item["status"] == "no_data":
            warnings.append(f"{item['dataset']}: no data found in the requested region")
        elif item["groups"]["live_capable_but_stale"]:
            warnings.append(
                f"{item['dataset']}: {item['groups']['live_capable_but_stale']} "
                f"live-capable records are stale (older than "
                f"{FRESHNESS_THRESHOLD_MINUTES} minutes)"
            )
    return ResultEnvelope(
        query={
            "region": region,
            "resolved_region": resolved_region.model_dump(exclude_none=True)
            if resolved_region
            else None,
            "bbox": region_bbox.model_dump() if region_bbox else None,
            "official_region_code": official_region_code,
            "dataset": dataset,
            "parking_scope": parking_scope,
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