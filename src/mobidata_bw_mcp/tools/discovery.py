from typing import Any

from ..clients import ckan, wfs
from ..config import DATASET_LICENSES, settings
from ..models import ResultEnvelope, source_info
from .common import limit_value, parse_timestamp


async def search_datasets(query: str, limit: int = 10) -> dict[str, Any]:
    """Search MobiData BW's catalogue by topic and return datasets, formats, and licences."""
    bounded = limit_value(limit)
    payload = await ckan.search(query, bounded)
    items = []
    for dataset in payload.get("results", []):
        items.append(
            {
                "title": dataset.get("title"),
                "slug": dataset.get("name"),
                "description": (dataset.get("notes") or "")[:500],
                "licence": dataset.get("license_title") or dataset.get("license_id"),
                "last_modified": dataset.get("metadata_modified"),
                "formats": sorted(
                    {
                        resource.get("format")
                        for resource in dataset.get("resources", [])
                        if resource.get("format")
                    }
                ),
            }
        )
    return ResultEnvelope(
        query={"query": query, "limit": bounded},
        count=len(items),
        truncated=payload.get("count", 0) > len(items),
        items=items,
        source=source_info("mobidata-bw-catalog", settings.ckan_url, "Varies by dataset"),
    ).compact()


async def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Get authoritative metadata and current resource URLs for one catalogue dataset."""
    dataset = await ckan.get(dataset_id)
    item = {
        "title": dataset.get("title"),
        "slug": dataset.get("name"),
        "description": dataset.get("notes"),
        "licence": dataset.get("license_title") or dataset.get("license_id"),
        "last_modified": dataset.get("metadata_modified"),
        "resources": [
            {key: resource.get(key) for key in ("name", "format", "url") if resource.get(key)}
            for resource in dataset.get("resources", [])
        ],
    }
    return ResultEnvelope(
        query={"dataset_id": dataset_id},
        count=1,
        items=[item],
        source=source_info(
            dataset.get("name", dataset_id),
            settings.ckan_url,
            item["licence"] or "Not specified",
        ),
        data_timestamp=parse_timestamp(dataset.get("metadata_modified")),
    ).compact()


async def list_layers() -> dict[str, Any]:
    """List current MobiData BW WFS layers and known geometry attributes; cached for 24 hours."""
    items = await wfs.list_layers()
    return ResultEnvelope(
        query={},
        count=len(items),
        items=items,
        source=source_info("geoserver-layers", settings.wfs_url, DATASET_LICENSES["wfs"]),
    ).compact()