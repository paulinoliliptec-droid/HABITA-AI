"""Official market prices beyond Portugal (afinamentos 2026-11-03, owner): a dated snapshot, like the INE one.

Each figure is a median computed by HABITA from an official open dataset of real transactions, never a model's number:

- Paris: DVF (Demandes de valeurs foncières, DGFiP, published by Etalab), sales of 2025 by arrondissement. A sale
  counts when it is one apartment (with or without outbuildings); price per m² = sale value / built area.
- New York City: NYC Department of Finance annualized sales (NYC Open Data ``w2pb-icbu``), sales of 2025 by borough,
  homes only (one to three family dwellings, co-ops, condos), above $10,000 (nominal transfers excluded). The dataset
  has no reliable area for apartments, so the figure is the median sale price.
- Singapore: HDB resale flat prices (data.gov.sg), the last 12 complete months, Singapore-wide, as S$ per m² of floor
  area. Public housing only: private homes are not in this dataset.

Refresh with ``python -m app.services.afford.international`` (network; writes ``data/international_snapshot.json``).
Lookup is offline and never raises: an unknown place has no figure.
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import sys
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data" / "international_snapshot.json"
DVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/communes/75/{code}.csv"
DVF_PAGE = "https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
NYC_API = "https://data.cityofnewyork.us/resource/w2pb-icbu.json"
NYC_PAGE = "https://data.cityofnewyork.us/d/w2pb-icbu"
HDB_API = "https://data.gov.sg/api/action/datastore_search"
HDB_RESOURCE = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
HDB_PAGE = "https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view"
NYC_BOROUGHS = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
NYC_HOMES = ("01 ", "02 ", "03 ", "09 ", "10 ", "12 ", "13 ", "15 ", "17 ")


# ── Lookup (offline) ─────────────────────────────────────────────────────────────────────────────────────────────

@lru_cache
def snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def paris_arrondissement(formatted_address: str) -> str | None:
    """75004 → "75104" (the INSEE code DVF uses); 75116 is the 16th like 75016."""
    m = re.search(r"\b750(\d{2})\b", formatted_address) or re.search(r"\b751(16)\b", formatted_address)
    if not m or not 1 <= int(m.group(1)) <= 20:
        return None
    return f"751{int(m.group(1)):02d}"


def nyc_borough(name: str | None) -> str | None:
    if not name:
        return None
    plain = name.removeprefix("The ").strip()
    return plain if plain in NYC_BOROUGHS.values() else None


def figures_for(jurisdiction_id: str, formatted_address: str, subdivision: str | None) -> list[dict]:
    """The market figures for a property in a covered city, each with its source; [] elsewhere."""
    snap = snapshot()
    out = []
    if jurisdiction_id == "fr/ile-de-france/paris/paris":
        code = paris_arrondissement(formatted_address)
        hit = snap.get("paris", {}).get("areas", {}).get(code or "")
        if hit:
            out.append({**snap["paris"]["meta"], **hit})
    elif jurisdiction_id == "us/new-york/new-york-city":
        hit = snap.get("nyc", {}).get("areas", {}).get(nyc_borough(subdivision) or "")
        if hit:
            out.append({**snap["nyc"]["meta"], **hit})
    elif jurisdiction_id == "sg/singapore":
        hit = snap.get("singapore", {}).get("areas", {}).get("Singapore")
        if hit:
            out.append({**snap["singapore"]["meta"], **hit})
    return out


# ── Build (network) ──────────────────────────────────────────────────────────────────────────────────────────────

def _median(values: list[float]) -> int:
    return int(round(statistics.median(values)))


def build_paris(get, year: int) -> dict:
    areas = {}
    for n in range(1, 21):
        code = f"751{n:02d}"
        rows = list(csv.DictReader(io.StringIO(get(DVF_URL.format(year=year, code=code)))))
        sales: dict[str, list[dict]] = {}
        for r in rows:
            if r["nature_mutation"] == "Vente":
                sales.setdefault(r["id_mutation"], []).append(r)
        per_m2 = []
        for rs in sales.values():
            locals_ = [r for r in rs if r["type_local"]]
            flats = [r for r in locals_ if r["type_local"] == "Appartement"]
            if len(flats) != 1 or any(r["type_local"] not in ("Appartement", "Dépendance") for r in locals_):
                continue
            try:
                value, area = float(flats[0]["valeur_fonciere"]), float(flats[0]["surface_reelle_bati"] or 0)
            except ValueError:
                continue
            if area >= 9 and 1_000 <= value / area <= 60_000:  # obvious data errors out
                per_m2.append(value / area)
        if per_m2:
            areas[code] = {"area": f"Paris {n}{'er' if n == 1 else 'e'} arrondissement", "value": _median(per_m2),
                           "count": len(per_m2)}
    meta = {"label": "Median price of apartments sold", "unit": "€/m²", "period": str(year),
            "source": "DVF — Demandes de valeurs foncières (DGFiP, Etalab)", "url": DVF_PAGE,
            "note": "Sales of a single apartment; price divided by built area."}
    return {"meta": meta, "areas": areas}


def build_nyc(get_json, year: int) -> dict:
    areas = {}
    for code, name in NYC_BOROUGHS.items():
        rows = get_json(NYC_API, {"$select": "sale_price,building_class_category", "$limit": "100000",
                                  "$where": f"borough='{code}' and sale_date between '{year}-01-01T00:00:00' "
                                            f"and '{year}-12-31T23:59:59'"})
        prices = [float(r["sale_price"]) for r in rows
                  if r.get("building_class_category", "").startswith(NYC_HOMES) and float(r.get("sale_price") or 0) > 10_000]
        if prices:
            areas[name] = {"area": name, "value": _median(prices), "count": len(prices)}
    meta = {"label": "Median sale price of homes", "unit": "US$", "period": str(year),
            "source": "NYC Department of Finance — annualized sales (NYC Open Data)", "url": NYC_PAGE,
            "note": "One to three family dwellings, co-ops and condos; sales above $10,000."}
    return {"meta": meta, "areas": areas}


def build_singapore(get_json, months: list[str]) -> dict:
    per_m2 = []
    for month in months:
        rows = get_json(HDB_API, {"resource_id": HDB_RESOURCE, "limit": "10000",
                                  "filters": json.dumps({"month": month})})["result"]["records"]
        per_m2 += [float(r["resale_price"]) / float(r["floor_area_sqm"]) for r in rows if float(r["floor_area_sqm"]) > 0]
    meta = {"label": "Median resale price of public housing (HDB) flats", "unit": "S$/m²",
            "period": f"{months[0]} to {months[-1]}", "source": "Housing & Development Board — resale flat prices "
            "(data.gov.sg)", "url": HDB_PAGE, "note": "Singapore-wide; public housing only, private homes not included."}
    return {"meta": meta, "areas": {"Singapore": {"area": "Singapore", "value": _median(per_m2), "count": len(per_m2)}}
            if per_m2 else {}}


def _last_complete_months(today: date, n: int = 12) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return sorted(out)


def main() -> None:  # pragma: no cover - network
    import httpx

    with httpx.Client(timeout=120, follow_redirects=True) as http:
        def get(url):
            r = http.get(url)
            r.raise_for_status()
            return r.text

        def get_json(url, params):
            r = http.get(url, params=params)
            r.raise_for_status()
            return r.json()

        today = datetime.now(UTC).date()
        data = {"retrieved_on": today.isoformat(), "paris": build_paris(get, 2025), "nyc": build_nyc(get_json, 2025),
                "singapore": build_singapore(get_json, _last_complete_months(today))}
    SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main()
