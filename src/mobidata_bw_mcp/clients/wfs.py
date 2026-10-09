import re
import xml.etree.ElementTree as ET
from typing import Any

from cachetools import TTLCache

from ..config import LAYER_GEOMETRY_FIELDS, settings
from ..models import BBox
from .http import SourceError, http

_capabilities: TTLCache[str, list[dict[str, str | None]]] = TTLCache(
    maxsize=1, ttl=settings.capabilities_ttl
)
_SAFE_FILTER = re.compile(r"^[\w\s.'(),=<>!%:+-]+$")
_FORBIDDEN_FILTER = re.compile(
    r"(;|--|/\*|\*/|\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|UNION)\b)", re.IGNORECASE
)


def validate_filter(cql_filter: str | None) -> str | None:
    if cql_filter is None:
        return None
    if len(cql_filter) > 500 or not _SAFE_FILTER.fullmatch(cql_filter):
        raise ValueError("CQL filter contains unsupported characters")
    if _FORBIDDEN_FILTER.search(cql_filter):
        raise ValueError("CQL filter contains a forbidden expression")
    return cql_filter


async def list_layers() -> list[dict[str, str | None]]:
    if "layers" in _capabilities:
        return _capabilities["layers"]
    text = await http.get_text(
        settings.wfs_url,
        {"service": "WFS", "version": "1.0.0", "request": "GetCapabilities"},
    )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceError("WFS returned invalid capabilities XML") from exc
    namespace = {"wfs": "http://www.opengis.net/wfs"}
    layers = []
    for feature_type in root.findall(".//wfs:FeatureType", namespace):
        name = feature_type.findtext("wfs:Name", namespaces=namespace)
        if not name or not name.startswith("MobiData-BW:"):
            continue
        layers.append(
            {
                "name": name,
                "title": feature_type.findtext("wfs:Title", namespaces=namespace),
                "geometry_attribute": LAYER_GEOMETRY_FIELDS.get(name),
            }
        )
    _capabilities["layers"] = layers
    return layers


async def features(
    layer: str,
    *,
    bbox: BBox | None = None,
    cql_filter: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    available = {item["name"] for item in await list_layers()}
    if layer not in available:
        raise ValueError(f"Unknown WFS layer: {layer}")
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": layer,
        "outputFormat": "application/json",
        "maxFeatures": limit,
    }
    if bbox:
        params["bbox"] = (
            f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat},EPSG:4326"
        )
    if validated := validate_filter(cql_filter):
        params["CQL_FILTER"] = validated
    return await http.get_json(settings.wfs_url, params)