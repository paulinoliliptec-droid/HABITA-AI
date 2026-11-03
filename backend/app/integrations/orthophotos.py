"""Official orthophotos by place (afinamentos 2026-11-03, owner: the aerial view for the new jurisdictions too).

Each source is a public WMS of a government mapping agency, asked for the same 1024 px square in EPSG:3857 as the DGT
one, so the image scale (and the areas SAM's outlines give) is known:

- DGT, mainland Portugal: ``Ortos2018-RGB``, CC BY 4.0 (see ``integrations.dgt.orthophoto``).
- IGN Géoplateforme, metropolitan France: ``ORTHOIMAGERY.ORTHOPHOTOS``, the BD ORTHO mosaic of the latest flights,
  under the Licence Ouverte / Etalab 2.0 (reuse, including modified, with the source named).
- NYS Statewide Digital Orthoimagery (New York State ITS Geospatial Services), ``Latest`` mosaic: a public State
  program whose imagery is offered for viewing and download; its WMS states no fees and no access constraints. New
  York City's counties were flown in 2024 and 2026.

Both services were checked on 2026-11-03 to answer a GetMap for Paris and Manhattan with real imagery. Singapore is
not here: the OneMap terms of use forbid storing or modifying the imagery beyond what they allow, and HABITA stores
the image with its outlines; that needs SLA's confirmation first.
"""

import httpx

from app.integrations.dgt.orthophoto import DGT_SOURCE, Orthophoto, OrthoSource, fetch_wms

IGN_SOURCE = OrthoSource(
    provider="IGN", service="https://data.geopf.fr/wms-r", layer="ORTHOIMAGERY.ORTHOPHOTOS", year=None,
    edition="BD ORTHO, latest", attribution="© IGN – Géoplateforme, BD ORTHO (Licence Ouverte 2.0)",
    extent=(-5.3, 41.2, 9.7, 51.2))
#: One layer per flight year (0 = 2025 … 3 = 2022, checked 2026-11-03); WMS draws them in order, so the oldest go first
#: and each place shows its most recent flight (New York City: 2024).
NYS_SOURCE = OrthoSource(
    provider="NYS", service="https://orthos.its.ny.gov/arcgis/services/wms/Latest/MapServer/WMSServer",
    layer="3,2,1,0", year=None, edition="latest flight, 2022–2025",
    attribution="NYS Statewide Digital Orthoimagery (NYS ITS Geospatial Services)", extent=(-79.9, 40.45, -71.8, 45.05))
#: Each source serves only its own jurisdiction, read from the resolved property (Codex aerial r1: a rectangle alone
#: would let a property just across a border through, and its square could hold imagery from the covered side).
JURISDICTION = {"DGT": ("PT", None), "IGN": ("FR", None), "NYS": ("US", "us/new-york")}
SOURCES = (DGT_SOURCE, IGN_SOURCE, NYS_SOURCE)


def source_for(lat: float, lng: float, country_code: str | None = None,
               region_id: str | None = None) -> OrthoSource | None:
    """The source for a point inside its jurisdiction. Without a country, none (the gate needs the jurisdiction)."""
    for s in SOURCES:
        country, region = JURISDICTION[s.provider]
        if s.covers(lat, lng) and country_code == country and (region is None or region_id == region):
            return s
    return None


class OfficialOrthophotoClient:
    """The official orthophoto around a point, from the agency that covers it."""

    def __init__(self, http: httpx.AsyncClient, *, timeout_seconds: float = 30.0) -> None:
        self._http, self._timeout = http, timeout_seconds

    def source_for(self, lat: float, lng: float, country_code: str | None = None,
                   region_id: str | None = None) -> OrthoSource | None:
        return source_for(lat, lng, country_code, region_id)

    async def fetch(self, lat: float, lng: float, half_m: float, source: OrthoSource | None = None) -> Orthophoto | None:
        """``source`` is the one the jurisdiction gate chose; without it, nothing is fetched."""
        if source is None:
            return None
        return await fetch_wms(self._http, source, lat, lng, half_m, self._timeout)
