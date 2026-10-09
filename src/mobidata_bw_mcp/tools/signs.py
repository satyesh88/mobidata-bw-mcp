import re
from typing import Any

from shapely import STRtree
from shapely.geometry import Point, box, shape

from ..clients import geocode, static_files
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict
from ..models import BBox, LocationInput, ResultEnvelope, source_info
from .common import latest_datetime

TRUCK_CODES = {"253", "262", "263", "264", "265", "266", "277"}
SIGN_MEANINGS = {
    "253": "Vehicles over 3.5 t prohibited",
    "262": "Actual mass limit",
    "263": "Axle load limit",
    "264": "Width limit",
    "265": "Height limit",
    "266": "Length limit",
    "277": "Truck overtaking prohibited",
}
SIGN_CAVEATS = [
    "Traffic-sign data is not legally binding and municipal coverage varies.",
    "Supplementary signs such as 'Lieferverkehr frei' are not included; "
    "restrictions may have exceptions.",
]
_tree: STRtree | None = None
_features: list[dict[str, Any]] = []


def normalized_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?:DE:)?(\d{3})", value)
    return match.group(1) if match else value


def sign_value(value: str | None) -> float | None:
    if not value:
        return None
    suffix = value.split(":")[-1].split("-")[1:]
    if not suffix:
        return None
    text = ".".join(suffix).replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


async def sign_index() -> tuple[STRtree, list[dict[str, Any]]]:
    global _tree, _features
    if _tree is None:
        payload = await static_files.signs()
        _features = [item for item in payload.get("features", []) if item.get("geometry")]
        _tree = STRtree([shape(item["geometry"]) for item in _features])
    return _tree, _features


async def selected_signs(
    area: Any, codes: set[str] | None = None
) -> list[tuple[dict[str, Any], Point]]:
    tree, features = await sign_index()
    selected = []
    for index in tree.query(area, predicate="intersects"):
        feature = features[int(index)]
        point = shape(feature["geometry"])
        code = normalized_code(feature["properties"].get("Verkehrszeichennummer"))
        if codes is None or code in codes:
            selected.append((feature, point))
    return selected


async def find_traffic_signs(
    location: LocationInput | dict[str, Any] | None = None,
    bbox: BBox | dict[str, Any] | None = None,
    radius_m: int = 500,
    sign_codes: list[str] | None = None,
    truck_relevant_only: bool = False,
) -> dict[str, Any]:
    """Find traffic signs by radius or bbox. Results are advisory and omit supplementary signs."""
    if location is None and bbox is None:
        raise ValueError("location or bbox is required")
    resolved = await geocode.resolve(location) if location is not None else None
    parsed_bbox = BBox.model_validate(bbox) if bbox is not None else None
    if resolved:
        radius_bbox = bbox_around(resolved, radius_m)
        area = box(
            radius_bbox.min_lon,
            radius_bbox.min_lat,
            radius_bbox.max_lon,
            radius_bbox.max_lat,
        )
    else:
        area = box(
            parsed_bbox.min_lon,
            parsed_bbox.min_lat,
            parsed_bbox.max_lon,
            parsed_bbox.max_lat,
        )
    codes = {normalized_code(code) for code in sign_codes} if sign_codes else None
    if truck_relevant_only:
        codes = TRUCK_CODES if codes is None else codes & TRUCK_CODES
    records = await selected_signs(area, codes)
    items = []
    for feature, point in records:
        props = feature["properties"]
        raw_code = props.get("Verkehrszeichennummer")
        code = normalized_code(raw_code)
        distance = point.distance(Point(resolved.lon, resolved.lat)) * 111_320 if resolved else None
        if resolved and distance > radius_m:
            continue
        items.append(
            compact_dict(
                {
                    "sign_code": code,
                    "raw_sign_code": raw_code,
                    "meaning": SIGN_MEANINGS.get(code),
                    "value": sign_value(raw_code),
                    "municipality": props.get("Verwaltungsebene"),
                    "last_updated": props.get("LetzteAktualisierung"),
                    "lat": point.y,
                    "lon": point.x,
                    "distance_m": round(distance) if distance is not None else None,
                }
            )
        )
    if resolved:
        items.sort(key=lambda item: item["distance_m"])
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True) if resolved else None,
            "bbox": parsed_bbox.model_dump() if parsed_bbox else None,
            "radius_m": radius_m if resolved else None,
            "sign_codes": sign_codes,
            "truck_relevant_only": truck_relevant_only,
        },
        count=len(items),
        items=items,
        source=source_info("traffic-signs", settings.signs_url, DATASET_LICENSES["signs"]),
        data_timestamp=latest_datetime([item.get("last_updated") for item in items]),
        warnings=SIGN_CAVEATS,
    ).compact()