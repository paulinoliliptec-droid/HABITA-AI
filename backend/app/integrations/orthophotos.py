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
NYS_SOURCE = OrthoSource(
    provider="NYS", service="https://orthos.its.ny.gov/arcgis/services/wms/Latest/MapServer/WMSServer", layer="0",
    year=None, edition="latest", attribution="NYS Statewide Digital Orthoimagery (NYS ITS Geospatial Services)",
    extent=(-79.9, 40.45, -71.8, 45.05))
SOURCES = (DGT_SOURCE, IGN_SOURCE, NYS_SOURCE)


def source_for(lat: float, lng: float) -> OrthoSource | None:
    return next((s for s in SOURCES if s.covers(lat, lng)), None)


class OfficialOrthophotoClient:
    """The official orthophoto around a point, from the agency that covers it."""

    def __init__(self, http: httpx.AsyncClient, *, timeout_seconds: float = 30.0) -> None:
        self._http, self._timeout = http, timeout_seconds

    def source_for(self, lat: float, lng: float) -> OrthoSource | None:
        return source_for(lat, lng)

    async def fetch(self, lat: float, lng: float, half_m: float) -> Orthophoto | None:
        source = source_for(lat, lng)
        if source is None:
            return None
        return await fetch_wms(self._http, source, lat, lng, half_m, self._timeout)
