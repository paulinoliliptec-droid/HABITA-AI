"""HR-010: a photo, plan or document a user adds to a matter, and what HABITA read in it.

What is read is an observation from the user's file, never an official fact, and it never reaches the permit
verification: it can only add a condition to the report (AC10.5, AC10.6)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FileKind = Literal["photo", "plan", "document"]
#: none: the file has no GPS; near / far: GPS present, within or beyond the distance to the property.
GpsCheck = Literal["none", "near", "far"]
#: reading: recorded, being read now; read: observations recorded; unreadable: HABITA could not read the content;
#: failed: the reading service failed or the upload was interrupted.
ReadStatus = Literal["reading", "read", "unreadable", "failed"]

#: The consent wording the user accepted, by version. Changing the text needs a new version.
CONSENT_VERSION = "v1"


class MatterFile(BaseModel):
    file_id: str
    matter_id: str
    kind: FileKind
    content_type: Literal["image/jpeg", "image/png", "application/pdf"]
    size: int
    #: Of the file as the user sent it, before location and device data were removed.
    sha256: str
    added_at: datetime
    consent_version: str
    #: Read from the file before its metadata was removed; never proof of anything.
    captured_at: datetime | None = None
    gps_check: GpsCheck = "none"
    gps_distance_m: int | None = None
    read_status: ReadStatus
    observations: list[str] = Field(default_factory=list)
    model_id: str | None = None
