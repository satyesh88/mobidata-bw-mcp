#!/usr/bin/env python3
import asyncio
import time
from collections.abc import Awaitable, Callable

from mobidata_bw_mcp.clients import ckan, geocode, gtfs, parkapi, static_files, wfs
from mobidata_bw_mcp.models import BBox, Location
from mobidata_bw_mcp.tools.signs import normalized_code

HEILBRONN = Location(lat=49.1427, lon=9.2069, label="Heilbronn Hbf")


async def check_ckan() -> int:
    return len((await ckan.search("Fahrrad", 1)).get("results", []))


async def check_wfs() -> int:
    payload = await wfs.features(
        "MobiData-BW:transit_stops",
        bbox=BBox(min_lat=49.1327, min_lon=9.1969, max_lat=49.1527, max_lon=9.2169),
        limit=1,
    )
    features = payload.get("features", [])
    if not features:
        raise AssertionError("No transit stop found near Heilbronn Hbf")
    lon, lat = features[0]["geometry"]["coordinates"]
    if not (48 < lat < 50 and 8 < lon < 10):
        raise AssertionError(f"Unexpected WFS axis order: {lon}, {lat}")
    return len(features)


async def check_parkapi() -> int:
    records, _, _ = await parkapi.parking_sites(
        {"lat": HEILBRONN.lat, "lon": HEILBRONN.lon, "radius": 2000}, 1
    )
    return len(records)


async def check_roadworks() -> int:
    return len((await static_files.roadworks()).get("features", []))


async def check_signs() -> int:
    features = (await static_files.signs()).get("features", [])
    if features and "Verkehrszeichennummer" not in features[0].get("properties", {}):
        raise AssertionError("Traffic-sign schema changed")
    raw_codes = {
        feature.get("properties", {}).get("Verkehrszeichennummer")
        for feature in features
    }
    if "DE:277" in raw_codes and normalized_code("DE:277") != "277":
        raise AssertionError("Traffic-sign code normalization failed")
    return len(features)


async def check_gtfs() -> int:
    return len(await gtfs.departures({"limit": 1}))


async def check_nominatim() -> int:
    result = await geocode.resolve("Heilbronn Hauptbahnhof")
    if abs(result.lat - HEILBRONN.lat) > 0.1:
        raise AssertionError(f"Unexpected geocode result: {result}")
    return 1


async def run_check(name: str, check: Callable[[], Awaitable[int]]) -> bool:
    started = time.perf_counter()
    try:
        count = await check()
        elapsed = (time.perf_counter() - started) * 1000
        print(f"PASS  {name:<12} {elapsed:>8.0f} ms  {count:>7} items")
        return True
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        print(f"FAIL  {name:<12} {elapsed:>8.0f} ms  {exc}")
        return False


async def main() -> None:
    checks: list[tuple[str, Callable[[], Awaitable[int]]]] = [
        ("CKAN", check_ckan),
        ("WFS axis", check_wfs),
        ("ParkAPI", check_parkapi),
        ("Roadworks", check_roadworks),
        ("Signs", check_signs),
        ("GTFS", check_gtfs),
        ("Nominatim", check_nominatim),
    ]
    print("STATUS SOURCE        LATENCY    COUNT")
    results = []
    for name, check in checks:
        results.append(await run_check(name, check))
    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())