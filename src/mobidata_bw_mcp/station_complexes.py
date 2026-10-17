"""Verified station-complex aliases shared by the tools and bot."""

import re

HEILBRONN_COMPLEX_NAMES = {
    "heilbronn hbf",
    "heilbronn hauptbahnhof",
    "de:08121:26",
    "de:08121:26_parent",
    "heilbronn hbf/willy-brandt-platz",
    "heilbronn hbf/willy-brandt-pl.",
}


def canonical_station_input(value: str) -> str:
    if re.match(r"^de:08121:(?:26|1114|1115|1116)(?::|_|$)", value, re.IGNORECASE):
        return "Heilbronn Hbf"
    station = re.sub(
        r"\s+(?:Gleis|Gl\.?|Bstg|Bahnsteig)\s*\d+\w*\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return "Heilbronn Hbf" if station.casefold() in HEILBRONN_COMPLEX_NAMES else station
