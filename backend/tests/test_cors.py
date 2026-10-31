"""The browser calls the API from another origin: every method the site uses must pass the CORS preflight.

Found on the real site 2026-10-31: PUT (HR-011 Calculate) and DELETE (HR-010 delete a file) were refused by the
preflight, so the site said it could not reach its server. Server-side tests never send a preflight."""

import re
from pathlib import Path

import pytest

from tests.permit_fakes import make_client

ORIGIN = "https://habita.example"
FRONTEND = Path(__file__).parents[2] / "frontend" / "src"


def site_methods() -> set[str]:
    found = {"GET"}
    for f in FRONTEND.rglob("*.ts*"):
        found |= set(re.findall(r'method: "([A-Z]+)"', f.read_text(encoding="utf-8")))
    return found


def test_the_site_uses_put_and_delete():
    assert {"POST", "PUT", "DELETE"} <= site_methods()


@pytest.mark.parametrize("method", sorted(site_methods()))
def test_every_method_the_site_uses_passes_the_preflight(method):
    with make_client(backend_cors_origins=ORIGIN) as client:
        res = client.options("/api/permit/matters/pm_0000000000000001/afford", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type"})
    assert res.status_code == 200, (method, res.status_code)
    assert method in res.headers["access-control-allow-methods"]
