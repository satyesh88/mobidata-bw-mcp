from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = None


class BBox(BaseModel):
    min_lat: float = Field(ge=-90, le=90)
    min_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def ordered(self) -> "BBox":
        if self.min_lat >= self.max_lat or self.min_lon >= self.max_lon:
            raise ValueError("bbox minimums must be lower than maximums")
        return self


class RoutePoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Vehicle(BaseModel):
    weight_t: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)


class SourceInfo(BaseModel):
    dataset: str
    endpoint: str
    licence: str
    attribution: str


class ResultEnvelope(BaseModel):
    query: dict[str, Any]
    count: int
    truncated: bool = False
    items: list[dict[str, Any]]
    source: SourceInfo
    data_timestamp: datetime | None = None
    warnings: list[str] = Field(default_factory=list)

    def compact(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


LocationInput = str | Location


def source_info(dataset: str, endpoint: str, licence: str) -> SourceInfo:
    return SourceInfo(
        dataset=dataset,
        endpoint=endpoint,
        licence=licence,
        attribution=f"Daten: MobiData BW® / NVBW und Datengeber, {licence}",
    )