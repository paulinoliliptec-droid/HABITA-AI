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

#: What a file can point out, from a closed list. Each one adds a fixed sentence saying what to confirm (CHECK_TEXT);
#: the model only chooses from the list and never writes that sentence.
FileCheck = Literal["several_entrances", "possible_structural_wall", "kitchen_or_bathroom", "facade_or_window",
                    "several_floors"]

CHECK_TEXT: dict[str, str] = {
    "several_entrances": "Your file seems to show more than one entrance. If you plan to divide the property, confirm "
                         "with the Câmara Municipal that each unit would have its own exit to a common part or the "
                         "street.",
    "possible_structural_wall": "Your file shows walls that may carry weight. Before removing or opening any wall, "
                                "confirm with a structural engineer and the Câmara Municipal.",
    "kitchen_or_bathroom": "Your file shows a kitchen or a bathroom. If you plan to move water or drainage points, "
                           "confirm with the Câmara Municipal whether that needs prior control.",
    "facade_or_window": "Your file shows a facade, a window or a balcony. Before changing them, confirm with the "
                        "Câmara Municipal whether the works need prior control.",
    "several_floors": "Your file shows more than one floor. Confirm the licensed use of each floor with the Câmara "
                      "Municipal.",
}

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
    #: What to confirm, from the closed list; shown with HABITA's fixed text, never the model's.
    checks: list[FileCheck] = Field(default_factory=list)
    #: HR-012: whether the reader saw any person. None (not read, or read before this was asked) counts as yes.
    people_visible: bool | None = None
    model_id: str | None = None
