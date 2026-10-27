"""Jurisdiction contract.

A jurisdiction adapter turns a geocoded location into the administrative
hierarchy that governs it and, where the country is modelled, the competent
local authority. Adapters only interpret what the geocoder returned: when
something cannot be determined they leave it ``None`` rather than guess.

Hierarchy
    ``levels`` runs from the country down. Level types are country-neutral:

        country      the sovereign state
        region       first-order division      PT distrito / região autónoma, US state, FR région
        subregion    second-order division     US county, FR département
        municipality the local government unit that holds permitting competence
                     (PT município, US incorporated city, FR commune); never a postal
                     place used as a stand-in
        subdivision  a division below the municipality (PT freguesia, FR arrondissement)
        overlay      special districts and zones (historic, flood, coastal); reserved,
                     nothing produces it yet

    ``locality`` is separate: the postal/settlement name ("Parede", "Cascais") used
    for display and disambiguation. It carries no administrative meaning.

Identity
    Every level and authority has an ``id``: a lowercase ASCII path built from the
    country code and slugged names, e.g. ``pt/lisboa/cascais``. Names are
    display-only. IDs from a *modelled* adapter are built from names in the
    country's official language and are stable across UI languages. IDs from
    the generic adapter (``coverage == "unmodelled"``) are provisional and may
    change once a country adapter exists.
"""

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from app.integrations.maps.geocoding import GeocodedLocation

LevelType = Literal["country", "region", "subregion", "municipality", "subdivision", "overlay"]
Coverage = Literal["modelled", "unmodelled"]


@dataclass(frozen=True)
class JurisdictionLevel:
    type: LevelType
    id: str
    name: str
    #: Local term for the level, for display: "District", "Municipality", "State".
    label: str


@dataclass(frozen=True)
class SourceRef:
    title: str
    reference: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Authority:
    id: str
    name: str
    #: Machine-readable kind, e.g. "municipal_executive".
    kind: str
    #: The jurisdiction level this authority acts for.
    jurisdiction_id: str
    competence: str
    sources: tuple[SourceRef, ...] = ()


@dataclass(frozen=True)
class Jurisdiction:
    #: The most specific governing level: the municipality when known, else the deepest level.
    id: str
    country_code: str
    levels: tuple[JurisdictionLevel, ...]
    locality: str | None
    local_authority: Authority | None
    coverage: Coverage
    source: str = "google_maps"

    def level(self, level_type: LevelType) -> JurisdictionLevel | None:
        return next((lvl for lvl in self.levels if lvl.type == level_type), None)


class JurisdictionAdapter(ABC):
    #: Adapter identifier recorded in provenance.
    key: str
    #: Bumped whenever the adapter's output for the same input can change.
    version: int
    #: Language to geocode in so local names come back in their official form.
    #: ``None`` keeps whatever language the first lookup used.
    official_language: str | None = None

    @abstractmethod
    def resolve(self, location: GeocodedLocation) -> Jurisdiction: ...


def slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def child_id(parent_id: str, name: str) -> str:
    return f"{parent_id}/{slug(name)}"


def country_level(location: GeocodedLocation) -> JurisdictionLevel | None:
    comp = location.component("country")
    if comp is None:
        return None
    code = comp.short_name.upper()
    return JurisdictionLevel(type="country", id=code.lower(), name=comp.long_name, label="Country")
