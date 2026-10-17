"""Log tool arguments without message bodies or precise location coordinates."""

import re
from typing import Any

_PRIVATE_FIELDS = {"question", "user_text", "prompt", "history", "messages", "message"}
_COORDINATE_FIELDS = {
    "lat",
    "lon",
    "latitude",
    "longitude",
    "coordinates",
    "bbox",
    "min_lat",
    "max_lat",
    "min_lon",
    "max_lon",
}


def logged_arguments(value: Any, key: str = "") -> Any:
    if key.casefold() in _PRIVATE_FIELDS:
        return "[redacted]"
    if isinstance(value, dict):
        return {name: logged_arguments(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [logged_arguments(item, key) for item in value]
    if isinstance(value, (float, int)) and key.casefold() in _COORDINATE_FIELDS:
        return round(value, 3)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\.\d+\s*,\s*-?\d+\.\d+\s*", value):
        return ",".join(f"{float(part):.3f}" for part in value.split(","))
    return value
