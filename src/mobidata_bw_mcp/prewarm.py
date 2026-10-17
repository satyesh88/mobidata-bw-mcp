"""Best-effort background cache warming shared by HTTP and stdio servers."""

import asyncio
import logging
import time

from .clients import bfrk, geocode, gtfs, parkapi
from .tools import signs

LOG = logging.getLogger(__name__)
BFRK_FILES = (
    "Haltestelle",
    "Haltesteig",
    "Aufzug",
    "Rampe",
    "Toilette",
    "Treppe",
    "Engstelle",
    "Parkplatz",
)


async def _parking(name: str) -> None:
    location = await geocode.resolve(name)
    await parkapi.nearest_parking_sites(
        {"lat": location.lat, "lon": location.lon, "purpose": "CAR"}, 1000
    )


async def prewarm() -> None:
    started = time.monotonic()

    async def warm(awaitable) -> None:
        try:
            async with asyncio.timeout(45):
                await awaitable
        except Exception as exc:
            LOG.warning("prewarm source failed type=%s", type(exc).__name__)

    jobs = [
        bfrk.table(mode, f"BFRK_{entity}.csv") for mode in bfrk.DATASETS for entity in BFRK_FILES
    ]
    jobs += [signs.sign_index()]
    for name in ("Heilbronn Hbf", "Stuttgart Hbf"):
        jobs.extend((_parking(name), gtfs.resolve_stop_ids(name)))
    await asyncio.gather(*(warm(job) for job in jobs))
    LOG.info("prewarm done in %.2f s", time.monotonic() - started)
