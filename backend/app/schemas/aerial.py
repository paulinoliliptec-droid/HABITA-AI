"""Seen from the air: what SAM 3.1 finds on the official DGT orthophoto around a property (owner, 2026-11-01).

An observation from imagery, like a file reading: never an official fact, never a parcel boundary, never proof that
something is or isn't licensed. It can only add a condition to confirm with the Câmara Municipal."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AerialKind = Literal["building", "small_building", "pool"]
#: What a finding asks the user to confirm, from a closed list; HABITA's fixed text, never the model's.
AerialCheck = Literal["aerial_small_building", "aerial_pool"]

AERIAL_CHECK_TEXT: dict[str, str] = {
    "aerial_small_building": "A small separate building is visible from the air near the property. Confirm with the "
                             "Câmara Municipal that it is licensed.",
    "aerial_pool": "A swimming pool is visible from the air near the property. Confirm with the Câmara Municipal that "
                   "it is licensed.",
}
AERIAL_NOTICE = ("Seen from the air on the DGT orthophoto of {year}, segmented by Meta SAM 3.1. Outlines and areas are "
                 "approximate, may miss recent works, are not a survey or a parcel boundary, and prove no licence.")
#: The orthophotos are CC BY 4.0 (dados.gov.pt); this is DGT's attribution text.
AERIAL_ATTRIBUTION = "Informação geográfica cedida pela Direção-Geral do Território (CC BY 4.0)."


class AerialSource(BaseModel):
    provider: Literal["DGT", "IGN", "NYS"] = "DGT"
    service: str
    layer: str
    #: None for a mosaic of the latest flights (IGN, NYS).
    year: int | None
    edition: str | None = None
    #: The source's attribution (defaults to DGT's, for analyses stored before 2026-11-03).
    attribution: str = AERIAL_ATTRIBUTION
    crs: Literal["EPSG:3857"] = "EPSG:3857"
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    metres_per_pixel: float
    sha256: str
    retrieved_at: datetime


class AerialObject(BaseModel):
    kind: AerialKind
    #: m², rounded to 5; from the mask's pixels and the image scale.
    area_m2: int
    #: From the geocoded point to the nearest pixel of the object, metres.
    distance_m: int
    #: The geocoded point falls on this object.
    at_point: bool


class AerialReport(BaseModel):
    aerial_id: str
    property_id: str
    created_at: datetime
    source: AerialSource
    model_id: str
    prompts: list[str]
    #: Objects within this distance of the point are listed (the geocoding's own uncertainty).
    radius_m: int
    objects: list[AerialObject]
    checks: list[AerialCheck]
