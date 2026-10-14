import csv
import io
from pathlib import PurePosixPath
from typing import Any

from cachetools import TTLCache

from ..config import settings
from . import ckan
from .http import SourceError, http

DATASETS = {
    "SPNV": "bfrk-barrierefreiheit-an-bw-bahnhoefen",
    "OEPNV": "bfrk-barrierefreiheit-an-bw-haltestellen",
}

_table_cache: TTLCache[tuple[str, str], list[dict[str, str]]] = TTLCache(
    maxsize=32, ttl=settings.bfrk_ttl
)


def parse_csv(text: str) -> list[dict[str, str]]:
    """Parse a BFRK semicolon CSV while preserving localized source values."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=";")
    return [
        {str(key).strip(): (value or "").strip() for key, value in row.items()}
        for row in reader
    ]


async def resource_url(mode: str, filename: str) -> str:
    normalized_mode = mode.upper()
    if normalized_mode not in DATASETS:
        raise ValueError("mode must be SPNV or OEPNV")
    package = await ckan.get(DATASETS[normalized_mode])
    normalized_filename = filename.casefold()
    for resource in package.get("resources", []):
        url = str(resource.get("url") or "")
        resource_name = str(resource.get("name") or "")
        if (
            PurePosixPath(url).name.casefold() == normalized_filename
            or resource_name.casefold() == normalized_filename
        ):
            return url
    raise SourceError(f"BFRK resource not found: {normalized_mode}/{filename}")


async def table(mode: str, filename: str) -> list[dict[str, str]]:
    key = (mode.upper(), filename.casefold())
    if key not in _table_cache:
        url = await resource_url(*key)
        _table_cache[key] = parse_csv(await http.get_text(url))
    return _table_cache[key]


async def joined_stop(mode: str, stop_id: str) -> dict[str, Any]:
    stop_rows = await table(mode, "BFRK_Haltestelle.csv")
    stop = next(
        (
            row
            for row in stop_rows
            if (row.get("ID") or row.get("HST_DHID")) == stop_id
        ),
        None,
    )
    if stop is None:
        raise ValueError(f"Unknown BFRK stop: {stop_id}")
    filenames = (
        "BFRK_Haltesteig.csv",
        "BFRK_Aufzug.csv",
        "BFRK_Rampe.csv",
        "BFRK_Toilette.csv",
        "BFRK_Treppe.csv",
        "BFRK_Engstelle.csv",
        "BFRK_Parkplatz.csv",
    )
    joined: dict[str, Any] = {"Haltestelle": stop}
    for filename in filenames:
        entity = filename.removeprefix("BFRK_").removesuffix(".csv")
        rows = await table(mode, filename)
        joined[entity] = [row for row in rows if row.get("HST_DHID") == stop_id]
    return joined