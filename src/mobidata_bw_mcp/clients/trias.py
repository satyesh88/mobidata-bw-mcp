"""NVBW TRIAS 1.2 XML transport. Credentials and XML bodies are never logged."""

import asyncio
import hashlib
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, ParseError, SubElement, tostring

import httpx
from cachetools import TTLCache
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from ..config import settings
from ..models import Location
from .http import SourceError

NS = {"t": "http://www.vdv.de/trias", "s": "http://www.siri.org.uk/siri"}
_CACHE: TTLCache[tuple, Element] = TTLCache(maxsize=128, ttl=30)
_STOPS: TTLCache[tuple, "StopRef"] = TTLCache(maxsize=512, ttl=86400)
_SEMAPHORE = asyncio.Semaphore(2)
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StopRef:
    ref: str
    name: str


class TriasError(SourceError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"TRIAS {code}; no live information is available.")


def configuration() -> tuple[str, str]:
    key = os.getenv("TRIAS_REQUESTOR_REF", "").strip()
    url = os.getenv("TRIAS_URL", "https://efa-bw.de/trias").strip()
    if not key:
        raise TriasError("not_configured")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise TriasError("invalid_endpoint")
    return url, key


def add(parent: Element, name: str, value: object | None = None) -> Element:
    node = SubElement(parent, name)
    if value is not None:
        node.text = str(value)
    return node


def utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def location(
    parent: Element, name: str, value: Location | str | StopRef, when: datetime | None = None
) -> None:
    node = add(parent, name)
    ref = add(node, "LocationRef")
    if isinstance(value, (str, StopRef)):
        add(ref, "StopPointRef", value.ref if isinstance(value, StopRef) else value)
        label = value.name if isinstance(value, StopRef) else value
    else:
        position = add(ref, "GeoPosition")
        add(position, "Longitude", value.lon)
        add(position, "Latitude", value.lat)
        label = value.label or "Selected location"
    # LocationName is required by LocationRefStructure, even for coordinates/IDs.
    add(add(ref, "LocationName"), "Text", label)
    if when is not None:
        add(node, "DepArrTime", utc(when))
    if isinstance(value, Location):
        access = add(node, "IndividualTransportOptions")
        add(access, "Mode", "walk")
        add(access, "MaxDuration", "PT15M")


async def request(payload: Element) -> Element:
    url, key = configuration()
    cache_key = (url, hashlib.sha256(key.encode()).digest(), tostring(payload))
    if cache_key in _CACHE:
        return deepcopy(_CACHE[cache_key])
    root = Element("Trias", {"version": "1.2", "xmlns": NS["t"], "xmlns:siri": NS["s"]})
    service = add(root, "ServiceRequest")
    add(service, "siri:RequestTimestamp", utc(datetime.now(UTC)))
    add(service, "siri:RequestorRef", key)
    add(service, "RequestPayload").append(payload)
    started = time.monotonic()
    outcome = "ok"
    try:
        async with (
            asyncio.timeout(12),
            _SEMAPHORE,
            httpx.AsyncClient(
                timeout=10,
                follow_redirects=False,
                headers={
                    "User-Agent": settings.user_agent,
                    "Content-Type": "application/xml",
                    "Accept": "application/xml",
                },
            ) as client,
        ):
            response = await client.post(url, content=tostring(root, encoding="utf-8"))
        if response.status_code in {401, 403}:
            raise TriasError("authentication_failed")
        if response.status_code in {408, 504}:
            raise TriasError("source_timeout")
        if response.status_code != 200:
            raise TriasError("source_unavailable")
        if len(response.content) > 5_000_000:
            raise TriasError("response_too_large")
        document = fromstring(response.content)
        # Do not expose echoed credentials or upstream diagnostic text in tool results.
        for node in document.iter():
            if node.text:
                node.text = node.text.replace(key, "[redacted]")
            if node.tail:
                node.tail = node.tail.replace(key, "[redacted]")
        if document.tag != f"{{{NS['t']}}}Trias":
            raise TriasError("invalid_response")
        if any(
            (node.text or "").strip().lower() in {"false", "0"}
            for node in document.findall(".//s:Status", NS)
        ):
            raise TriasError("request_rejected")
        expected = payload.tag.removesuffix("Request") + "Response"
        delivery = document.find(f".//t:{expected}", NS)
        if delivery is None:
            raise TriasError("request_rejected")
        errors = delivery.findall("t:ErrorMessage", NS)
        # TRIAS reports legitimate empty searches as ErrorMessage codes.
        # These are not network/auth failures and must not trigger scheduled fallback.
        empty_codes = {"-4030", "-4000"}  # STOPEVENT_NOEVENTFOUND, TRIP_NOTRIPFOUND
        if errors and any(
            (error.findtext("t:Code", namespaces=NS) or "").strip() not in empty_codes
            for error in errors
        ):
            raise TriasError("service_error")
        _CACHE[cache_key] = deepcopy(document)
        return document
    except (httpx.TimeoutException, TimeoutError):
        outcome = "source_timeout"
        raise TriasError(outcome) from None
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except httpx.HTTPError:
        outcome = "source_unavailable"
        raise TriasError(outcome) from None
    except (ParseError, DefusedXmlException):
        outcome = "invalid_response"
        raise TriasError(outcome) from None
    except TriasError as error:
        outcome = error.code
        raise
    finally:
        LOGGER.info(
            "trias request=%s duration_ms=%.0f outcome=%s",
            payload.tag,
            (time.monotonic() - started) * 1000,
            outcome,
        )


async def resolve_station(name: str) -> StopRef:
    """Resolve station names through TRIAS itself; cache public stop references for 24 h."""
    url, key = configuration()
    cache_key = (url, hashlib.sha256(key.encode()).digest(), name.strip().casefold())
    if cache_key in _STOPS:
        return _STOPS[cache_key]
    payload = Element("LocationInformationRequest")
    add(add(payload, "InitialInput"), "LocationName", name)
    restrictions = add(payload, "Restrictions")
    add(restrictions, "Type", "stop")
    add(restrictions, "NumberOfResults", 3)
    document = await request(payload)
    for node in document.findall(".//t:StopPoint", NS):
        ref = node.findtext("t:StopPointRef", namespaces=NS)
        label = node.findtext("t:StopPointName/t:Text", namespaces=NS)
        if ref and label:
            stop = StopRef(ref, label)
            _STOPS[cache_key] = stop
            return stop
    raise TriasError("location_not_found")


async def nearby_stops(value: Location) -> list[StopRef]:
    """Discover up to three nearby stop groups in a 500 m circle before a stop-event query."""
    payload = Element("LocationInformationRequest")
    initial = add(payload, "InitialInput")
    circle = add(add(initial, "GeoRestriction"), "Circle")
    center = add(circle, "Center")
    add(center, "Longitude", value.lon)
    add(center, "Latitude", value.lat)
    add(circle, "Radius", 500)
    restrictions = add(payload, "Restrictions")
    add(restrictions, "Type", "stop")
    add(restrictions, "NumberOfResults", 3)
    document = await request(payload)
    stops = []
    for node in document.findall(".//t:StopPoint", NS):
        ref = node.findtext("t:StopPointRef", namespaces=NS)
        label = node.findtext("t:StopPointName/t:Text", namespaces=NS)
        if ref and label and not any(stop.ref == ref for stop in stops):
            stops.append(StopRef(ref, label))
    if not stops:
        raise TriasError("location_not_found")
    return stops[:3]
