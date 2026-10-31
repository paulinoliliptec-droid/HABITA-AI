"""HR-011: official price statistics from INE, by municipality and parish, from a dated snapshot in the repository.

The snapshot holds the latest period of two INE indicators: the median bank valuation (€/m², monthly, by municipality
and construction type) and the median sale price of family dwellings over the last 12 months (€/m², quarterly, by
municipality and parish). Refresh it with ``python -m app.services.afford.ine``. A place is found by name inside its
municipality; a name that matches more than one municipality finds nothing (AC11.12)."""

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data" / "ine_snapshot.json"
INDICATORS = {"bank_valuation": "0012248", "sale_median": "0012246"}
API = "https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd={code}&lang=PT"


def _key(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    plain = re.sub(r"\(.*?\)", " ", plain)  # INE qualifies homonyms: "Lagoa (R.A.A.)", "Calheta (R.A.M.)"
    return " ".join(plain.replace("-", " ").split())


def _islands(name: str) -> str | None:
    """Which autonomous region a name or a region level points to: "raa" (Azores), "ram" (Madeira) or None."""
    k = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    if "r.a.a" in k or "acores" in k or "azores" in k:
        return "raa"
    if "r.a.m" in k or "madeira" in k:
        return "ram"
    return None


@lru_cache
def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Place:
    municipality: str
    bank_valuation: dict[str, int]
    municipal_sale_median: int | None
    parish: str | None
    parish_sale_median: int | None


def find(municipality: str | None, parish: str | None = None, region: str | None = None) -> Place | None:
    """The municipality by name, told apart from a homonym only by its region (mainland, Azores or Madeira); anything
    still ambiguous finds nothing."""
    if not municipality:
        return None
    places = snapshot()["places"]
    matches = [code for code, p in places.items() if len(code) == 7 and _key(p["name"]) == _key(municipality)]
    if len(matches) > 1:
        if region is None and _islands(municipality) is None:
            return None  # nothing tells the homonyms apart
        where = _islands(municipality) or _islands(region or "")
        matches = [c for c in matches if _islands(places[c]["name"]) == where]
    if len(matches) != 1:
        return None
    code = matches[0]
    m = places[code]
    parish_hit = next((p for c, p in places.items() if len(c) == 9 and c.startswith(code) and parish
                       and _key(p["name"]) == _key(parish)), None)
    return Place(municipality=m["name"], bank_valuation=m.get("bank_valuation", {}),
                 municipal_sale_median=m.get("sale_median"), parish=parish_hit["name"] if parish_hit else None,
                 parish_sale_median=parish_hit.get("sale_median") if parish_hit else None)


def refresh(path: Path = SNAPSHOT) -> None:  # pragma: no cover - a maintenance step with network access
    import httpx
    raw = {k: httpx.get(API.format(code=c), timeout=180).json()[0] for k, c in INDICATORS.items()}
    val, sal = raw["bank_valuation"], raw["sale_median"]
    places: dict[str, dict] = {}

    def num(row):
        try:
            return int(row["valor"])
        except (KeyError, ValueError, TypeError):
            return None

    for row in val["Dados"][val["UltimoPref"]]:
        if len(row["geocod"]) == 7 and (v := num(row)):
            p = places.setdefault(row["geocod"], {"name": row["geodsg"]})
            p.setdefault("bank_valuation", {})[{"T": "total", "1": "apartment", "2": "house"}[row["dim_3"]]] = v
    for row in sal["Dados"][sal["UltimoPref"]]:
        g = row["geocod"]
        if len(g) in (7, 9) and g.startswith("1") and row["dim_3"] == "T" and (v := num(row)):
            places.setdefault(g, {"name": row["geodsg"]})["sale_median"] = v
    source = {k: {"indicator": INDICATORS[k], "title": r["IndicadorDsg"], "period": r["UltimoPref"],
                  "updated": r["DataUltimoAtualizacao"], "url": f"https://www.ine.pt/xurl/indx/{INDICATORS[k]}"}
              for k, r in raw.items()}
    source |= {"publisher": "Instituto Nacional de Estatística (INE)", "extracted": val["DataExtracao"][:10]}
    path.write_text(json.dumps({"source": source, "places": dict(sorted(places.items()))}, ensure_ascii=False,
                               indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    refresh(Path(sys.argv[1]) if len(sys.argv) > 1 else SNAPSHOT)
