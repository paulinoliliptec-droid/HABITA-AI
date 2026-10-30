"""HR-003 PlanningContextResolver: zoning only from a trusted official layer; otherwise a useful manual fallback."""

from datetime import UTC, datetime

import pytest

from app.schemas.sources import OfficialSource, SourceVerification, ZoningClassification
from app.services.planning.cascais import cascais_resolver
from app.services.planning.resolver import LayerFeature, LayerQueryResult, PlanningContextService, decide
from app.services.sources.catalog import ALL_SOURCES, CASCAIS, VERIFIED_ON
from app.services.sources.registry import OfficialSourceRegistry
from app.services.sources.repository import InMemorySourceRepository
from tests.permit_fakes import make_client, resolve_cascais

LAYER = OfficialSource(
    source_id="cascais-test-zoning-layer", jurisdiction_id=CASCAIS, title="Test PDM zoning layer",
    source_type="gis_service", official_url="https://geocascais.cascais.pt/geoserver/ows", publisher="Câmara",
    geographic_scope="municipality", regulatory_scope=["land_use_planning"], retrieval_method="wms_getfeatureinfo",
    machine_readable=True, status="trusted", authority_class="official_dataset",
    provenance=SourceVerification(added_by="curated", verified_on=VERIFIED_ON, verified_by="tester"),
)
CENTRAL = ZoningClassification(land_class="Solo urbano", category="Espaços centrais", code="EC", label="Espaços centrais")
RESIDENTIAL = ZoningClassification(land_class="Solo urbano", category="Espaços habitacionais", code="EH",
                                   label="Espaços habitacionais")


class FakeLayer:
    source_id = LAYER.source_id

    def __init__(self, result: LayerQueryResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def query_point(self, lat, lng):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def found(*classes, distance=80.0) -> LayerQueryResult:
    return LayerQueryResult([LayerFeature(c, f"pdm_qualificacao.{n}") for n, c in enumerate(classes)], distance,
                            retrieved_at=datetime(2026, 10, 28, tzinfo=UTC))


@pytest.fixture
def app_client():
    with make_client() as c:
        yield c


@pytest.fixture
def cascais_property(app_client):
    pid = resolve_cascais(app_client)
    return app_client.portal.call(app_client.app.state.property_service.get, pid)


async def registry(*extra: OfficialSource) -> OfficialSourceRegistry:
    reg = OfficialSourceRegistry(InMemorySourceRepository(), ALL_SOURCES + extra)
    await reg.seed()
    return reg


# --- Cascais today: controlled manual confirmation ----------------------------------------


async def test_cascais_requires_manual_confirmation_with_exact_official_maps(cascais_property):
    context = await cascais_resolver(await registry()).resolve(cascais_property)
    assert context.status == "requires_manual_confirmation"
    assert context.classification is None and context.constraints == []  # never guessed
    assert context.reasons == ["no_machine_readable_layer"]
    assert context.instrument.source_id == "cascais-pdm" and "Aviso n.º 20120/2023" in context.instrument.version
    designations = [d.designation for d in context.documents_to_consult]
    assert designations[0] == "Planta de Ordenamento 01-02"  # land-use category first
    assert "Planta de Condicionantes 02-04" in designations
    for doc in context.documents_to_consult:
        assert doc.reason and (doc.official_url or "").startswith("https://www.cascais.pt/")
    assert context.competent_authority.name == "Câmara Municipal de Cascais"
    assert context.guidance.startswith("Planning classification requires confirmation against the official")
    assert "Câmara Municipal de Cascais" in context.guidance
    assert context.sources_verified_on == VERIFIED_ON and context.resolved_at.tzinfo is not None
    assert "cascais-pdm-planta-01-02" in context.sources_consulted


async def test_low_precision_is_reported_too(cascais_property):
    vague = cascais_property.model_copy(update={"precision": "area_center"})
    context = await cascais_resolver(await registry()).resolve(vague)
    assert context.status == "requires_manual_confirmation"
    assert set(context.reasons) == {"no_machine_readable_layer", "low_geocode_precision"}


async def test_without_a_trusted_instrument_nothing_is_presented_as_authoritative(cascais_property):
    reg = await registry()
    await reg.change_status("cascais-pdm", "retired", operator="ops", reason="test")
    context = await cascais_resolver(reg).resolve(cascais_property)
    assert context.status == "requires_manual_confirmation" and context.instrument is None


# --- the decision rules (future connectors) ------------------------------------------------


async def test_a_trusted_layer_with_one_clear_feature_resolves(cascais_property):
    layer = FakeLayer(found(CENTRAL))
    context = await cascais_resolver(await registry(LAYER), layer).resolve(cascais_property)
    assert context.status == "resolved" and context.classification == CENTRAL
    assert context.reasons == [] and context.documents_to_consult == []
    assert context.raw_reference == "pdm_qualificacao.0" and LAYER.source_id in context.sources_consulted
    assert context.source_retrieved_at == datetime(2026, 10, 28, tzinfo=UTC)


@pytest.mark.parametrize("result, precision, reason", [
    (found(CENTRAL, RESIDENTIAL), "rooftop", "multiple_features"),
    (found(distance=80.0), "rooftop", "no_feature_at_point"),
    (found(CENTRAL, distance=4.0), "rooftop", "near_class_boundary"),
    (found(CENTRAL, distance=None), "rooftop", "boundary_distance_unknown"),
    (found(CENTRAL), "approximate", "low_geocode_precision"),
    # CX-5: one feature, not one class; a distance must be finite and non-negative.
    (found(CENTRAL, CENTRAL), "rooftop", "multiple_features"),
    (found(CENTRAL, distance=float("nan")), "rooftop", "boundary_distance_unknown"),
    (found(CENTRAL, distance=float("inf")), "rooftop", "boundary_distance_unknown"),
    (found(CENTRAL, distance=-1.0), "rooftop", "boundary_distance_unknown"),
])
async def test_ambiguous_zoning_requires_manual_confirmation(cascais_property, result, precision, reason):
    prop = cascais_property.model_copy(update={"precision": precision})
    context = await cascais_resolver(await registry(LAYER), FakeLayer(result)).resolve(prop)
    assert context.status == "requires_manual_confirmation"
    assert reason in context.reasons and context.classification is None
    assert context.documents_to_consult  # still points to the official maps


async def test_an_untrusted_layer_is_never_queried(cascais_property):
    candidate = LAYER.model_copy(update={"status": "candidate"})
    layer = FakeLayer(found(CENTRAL))
    context = await cascais_resolver(await registry(candidate), layer).resolve(cascais_property)
    assert context.status == "requires_manual_confirmation" and "layer_source_not_trusted" in context.reasons
    assert layer.calls == 0


async def test_a_failing_layer_falls_back_to_manual_confirmation(cascais_property):
    context = await cascais_resolver(await registry(LAYER), FakeLayer(TimeoutError())).resolve(cascais_property)
    assert context.status == "requires_manual_confirmation" and "layer_query_failed" in context.reasons


def test_decide_without_a_layer():
    assert decide(None, "rooftop", 15.0) == (["no_machine_readable_layer"], None)


async def test_jurisdictions_without_a_resolver_are_not_supported(cascais_property):
    elsewhere = cascais_property.model_copy(update={"jurisdiction": cascais_property.jurisdiction.model_copy(
        update={"id": "pt/porto/porto", "levels": [lvl.model_copy(update={"id": lvl.id.replace("lisboa/cascais", "porto/porto")
                                                                         .replace("lisboa", "porto")})
                                                  for lvl in cascais_property.jurisdiction.levels]})})
    service = PlanningContextService([cascais_resolver(await registry())])
    context = await service.resolve(elsewhere)
    assert context.status == "not_supported" and context.instrument is None and context.documents_to_consult == []
    assert (await service.resolve(cascais_property)).status == "requires_manual_confirmation"


# --- API ------------------------------------------------------------------------------------


def test_planning_context_endpoint(app_client):
    pid = resolve_cascais(app_client)
    res = app_client.get(f"/api/property/{pid}/planning-context")
    assert res.status_code == 200
    body = res.json()
    assert body["planning_context"]["status"] == "requires_manual_confirmation"
    assert body["planning_context"]["documents_to_consult"][0]["designation"] == "Planta de Ordenamento 01-02"
    ids = [s["source_id"] for s in body["sources"]]
    assert ids[0] == "cascais-pdm" and "pt-rjue" in ids  # municipal instrument first, national after
    assert "cascais-geocascais" not in ids and all(s["status"] == "trusted" for s in body["sources"])
    assert app_client.get("/api/property/prp_0000000000000000/planning-context").status_code == 404
