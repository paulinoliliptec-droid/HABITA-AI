"""HR-011 AFFORD: what the works may cost, how they could be financed and what the property may be worth.

Every number here is computed by HABITA's code from named sources and the user's own figures; none is written by a
model. All of it is an estimate with no financial guarantee, and none of it changes a permit status (AC11.7, AC11.9)."""

from typing import Literal

from pydantic import BaseModel, Field

PropertyType = Literal["apartment", "house"]


class AffordInputs(BaseModel):
    """What the user tells HABITA; every figure is theirs, labelled as declared."""

    area_m2: float | None = Field(default=None, gt=0, le=100_000)
    property_type: PropertyType | None = None
    quote_low: float | None = Field(default=None, ge=0, le=100_000_000)
    quote_high: float | None = Field(default=None, ge=0, le=100_000_000)
    budget: float | None = Field(default=None, ge=0, le=100_000_000)
    rate_percent: float | None = Field(default=None, ge=0, le=30)
    years: int | None = Field(default=None, ge=1, le=50)
    down_payment: float | None = Field(default=None, ge=0, le=100_000_000)


class Figure(BaseModel):
    """One amount and where it comes from."""

    label: str
    low: float
    high: float
    likely: float | None = None
    #: Per m², for a figure built from a price per m².
    per_m2_low: float | None = None
    per_m2_high: float | None = None
    source: str
    author: str | None = None
    source_kind: Literal["reference_table", "user_declared", "official_statistics", "computed"]
    as_of: str | None = None
    url: str | None = None


class Scenario(BaseModel):
    key: Literal["lower", "likely", "higher"]
    cost: float
    #: Monthly payment, only when the user set a rate and a term.
    monthly_payment: float | None = None
    financed: float | None = None
    within_budget: bool | None = None
    assumptions: list[str]
    moves_it: list[str]


class AffordReport(BaseModel):
    inputs: AffordInputs
    costs: list[Figure] = Field(default_factory=list)
    #: Why no cost range is shown, when none is.
    costs_note: str | None = None
    fees_note: str
    scenarios: list[Scenario] = Field(default_factory=list)
    financing_note: str | None = None
    formula: str
    valuation: list[Figure] = Field(default_factory=list)
    valuation_note: str | None = None
    disclaimer: str
