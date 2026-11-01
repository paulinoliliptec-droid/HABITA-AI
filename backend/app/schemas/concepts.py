"""HR-012: a before/after concept made from the user's own photo. A concept is an illustration, never a project, an
authorisation, evidence or a cost (AC12.3, AC12.4)."""

from datetime import datetime

from typing import Literal

from pydantic import BaseModel


class ConceptOption(BaseModel):
    key: str
    label: str
    #: What the change is made from: one of the user's photos, or a plan.
    source: Literal["photo", "plan"] = "photo"


class Concept(BaseModel):
    concept_id: str
    matter_id: str
    file_id: str
    change: str
    change_label: str
    created_at: datetime
    model_id: str
