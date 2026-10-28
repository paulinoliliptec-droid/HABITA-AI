"""Curated official sources for Portugal (national) and Cascais (municipal).

Every URL below was checked on 2026-10-28 to respond from the official host with
the expected document type (the PDM maps and the Regulamento as PDF, linked from
the Câmara's page "PDM — compilação dos elementos constituintes em vigor"). No
URL is inferred: a source without a verified URL has ``official_url=None``.

National legislation stays a curated reference (the Diário da República serves
consolidated texts through a JavaScript application, so HABITA does not fetch
it); the PDM Regulamento and the urbanism FAQ are fetched and indexed as
official text by ``python -m app.maintenance ingest-sources``.
"""

from datetime import date

from app.schemas.sources import OfficialSource, SourceVerification

VERIFIED_ON = date(2026, 10, 28)
CASCAIS = "pt/lisboa/cascais"
CAMARA = f"{CASCAIS}:camara-municipal"
CASCAIS_FILES = "https://www.cascais.pt/sites/default/files"
PDM_PAGE = "https://www.cascais.pt/pdm-compilacao-dos-elementos-constituintes-em-vigor"
PDM_VERSION = (
    "PDM-Cascais 2015 revision (Aviso n.º 7212-B/2015), altered for the RJIGT by Aviso n.º 20120/2023, "
    "corrected by Aviso n.º 15687/2024/2; republished Regulamento"
)

_curated = SourceVerification(added_by="curated", verified_on=VERIFIED_ON, verified_by="HABITA source curation (HR-003)")


def _national(source_id: str, title: str, version: str, scope: list, url: str | None = None) -> OfficialSource:
    return OfficialSource(
        source_id=source_id, jurisdiction_id="pt", title=title, source_type="legislation", official_url=url,
        publisher="República Portuguesa (Diário da República)", geographic_scope="national", regulatory_scope=scope,
        version=version, retrieval_method="curated", machine_readable=False, status="trusted",
        authority_class="primary_law", provenance=_curated,
    )


def _cascais(source_id: str, title: str, source_type: str, url: str | None, **fields) -> OfficialSource:
    return OfficialSource(
        source_id=source_id, jurisdiction_id=CASCAIS, authority_id=CAMARA, title=title, source_type=source_type,
        official_url=url, publisher="Câmara Municipal de Cascais", geographic_scope="municipality",
        **{"retrieval_method": "manual", "machine_readable": False, "status": "trusted",
           "authority_class": "municipal_instrument", "provenance": _curated, **fields},
    )


def _map(code: str, kind: str, title: str, path: str, scope: list | None = None) -> OfficialSource:
    group = "Planta de Ordenamento" if kind == "ordenamento" else "Planta de Condicionantes"
    return _cascais(
        f"cascais-pdm-planta-{code.lower()}", f"PDM-Cascais — {group} {code}: {title}", "planning_map",
        f"{CASCAIS_FILES}/{path}", part_of="cascais-pdm", designation=f"{group} {code}",
        regulatory_scope=scope or ["land_use_planning"], version=PDM_VERSION,
    )


NATIONAL = (
    _national(
        "pt-rjue", "Regime Jurídico da Urbanização e da Edificação (RJUE)",
        "Decreto-Lei n.º 555/99 (consolidated), reformed by Decreto-Lei n.º 10/2024",
        ["licensing_procedure", "change_of_use", "unit_division", "competent_authority"],
        "https://diariodarepublica.pt/dr/detalhe/decreto-lei/555-1999-655682",
    ),
    _national("pt-simplex-urbanistico", "Simplex Urbanístico", "Decreto-Lei n.º 10/2024, de 8 de janeiro",
              ["licensing_procedure", "change_of_use"]),
    _national("pt-codigo-civil-propriedade-horizontal", "Código Civil — propriedade horizontal",
              "Código Civil, arts. 1414.º–1438.º-A (consolidated)", ["unit_division", "horizontal_property"]),
    _national("pt-rgeu", "Regulamento Geral das Edificações Urbanas (RGEU)",
              "Decreto-Lei n.º 38 382/51, as amended (incl. Decreto-Lei n.º 10/2024)", ["habitability", "unit_division"]),
)

PDM_MAPS = (
    _map("01-01", "ordenamento", "Classificação do Solo", "anexos/gerais/new/01-01_classificacao_do_solo.pdf"),
    _map("01-02", "ordenamento", "Qualificação do Solo", "anexos/gerais/new/10-pord_73542_1105po0102-qual_0.pdf"),
    _map("01-03", "ordenamento", "Estrutura Ecológica", "anexos/gerais/new/11-pord_73542_1105po0103-esec_0.pdf"),
    _map("01-05", "ordenamento", "Planos com Repercussão Territorial",
         "anexos/gerais/new/01-05_planos_com_repercussao_territorial.pdf"),
    _map("01-06", "ordenamento", "Património", "anexos/gerais/new/01-06_patrimonio.pdf"),
    _map("01-09", "ordenamento", "Regimes de Proteção — PNSC", "anexos/gerais/new/12-pord_73542_1105po0109-pnsc_0.pdf"),
    _map("01-10A", "ordenamento", "Regime de Proteção — POC-ACE (A)",
         "anexos/gerais/new/01-10a_regime_de_protecao_-_ocace_0.pdf"),
    _map("01-10B", "ordenamento", "Regime de Proteção — POC-ACE (B)",
         "anexos/gerais/new/01-10b_regime_de_protecao_-_ocace_0.pdf"),
    _map("02-01-01", "condicionantes", "Áreas Protegidas", "PDM/TOMO-B/TOMO-B-1-2_P-CND-020101.pdf"),
    _map("02-01-02", "condicionantes", "Valores e Recursos Naturais",
         "anexos/gerais/new/13-pcond_73543_1105co020102-vn_0.pdf"),
    _map("02-01-03A", "condicionantes", "Reserva Ecológica Nacional (A)", "anexos/gerais/new/02-01-3a_ren.pdf"),
    _map("02-01-03B", "condicionantes", "Reserva Ecológica Nacional (B)", "anexos/gerais/new/02-01-3b_ren.pdf"),
    _map("02-02A", "condicionantes", "Equipamento (A)", "anexos/gerais/new/02-02a_equipamento.pdf"),
    _map("02-02B", "condicionantes", "Equipamento (B)", "anexos/gerais/new/02-02b_equipamento.pdf"),
    _map("02-03", "condicionantes", "Infraestruturas", "anexos/gerais/new/14-pcond_73543_1105co0203-infr_0.pdf"),
    _map("02-04", "condicionantes", "Património", "anexos/gerais/new/02-04_patrimonio.pdf"),
    _map("02-05", "condicionantes", "Perigosidade de Incêndio Rural",
         "anexos/gerais/new/02-05_perigosidade_de_incendio_rural.pdf"),
)

CASCAIS_SOURCES = (
    _cascais(
        "cascais-pdm", "Plano Diretor Municipal de Cascais (PDM-Cascais) — Regulamento", "planning_instrument",
        f"{CASCAIS_FILES}/anexos/gerais/new/regulamento_pdm_em_vigor_1.pdf",
        retrieval_method="http_pdf", machine_readable=True, version=PDM_VERSION,
        regulatory_scope=["land_use_planning", "change_of_use", "unit_division"],
    ),
    _cascais(
        "cascais-pdm-elementos", "PDM-Cascais — compilação dos elementos constituintes em vigor", "official_html",
        PDM_PAGE, part_of="cascais-pdm", version=PDM_VERSION, regulatory_scope=["land_use_planning"],
    ),
    _cascais(
        "cascais-pdm-aviso-20120-2023", "Aviso n.º 20120/2023 — alteração do PDM-Cascais (adaptação ao RJIGT)",
        "official_pdf", f"{CASCAIS_FILES}/anexos/gerais/new/aviso_n.o_20120-2023.pdf", part_of="cascais-pdm",
        version="Aviso n.º 20120/2023", regulatory_scope=["land_use_planning"],
    ),
    _cascais(
        "cascais-pdm-aviso-15687-2024", "Aviso n.º 15687/2024/2 — correção material do PDM-Cascais", "official_pdf",
        f"{CASCAIS_FILES}/anexos/gerais/new/4-aviso_n.o_15687_2024_2.pdf", part_of="cascais-pdm",
        version="Aviso n.º 15687/2024/2", regulatory_scope=["land_use_planning"],
    ),
    _cascais(
        "cascais-urbanismo-faq",
        "Urbanismo — perguntas frequentes sobre pedidos de licenciamento e comunicação prévia", "procedure_page",
        f"{CASCAIS_FILES}/anexos/gerais/new/fqas.pdf", retrieval_method="http_pdf", machine_readable=True,
        authority_class="official_guidance", regulatory_scope=["licensing_procedure"],
    ),
    *PDM_MAPS,
    # The municipal GIS: reachable, but not validated for zoning. On 2026-10-28 its public WMS listed two
    # layers, neither from the PDM, and its WFS listed none. It stays a candidate until an operator
    # validates a documented PDM layer; HABITA does not probe undocumented endpoints.
    _cascais(
        "cascais-geocascais", "GeoCascais — sistema de informação geográfica municipal", "gis_service",
        "https://geocascais.cascais.pt/", retrieval_method="wms_getfeatureinfo", machine_readable=True,
        status="candidate", authority_class="official_dataset", regulatory_scope=["land_use_planning"],
        provenance=SourceVerification(
            added_by="curated", notes="Public WMS reachable; no PDM zoning layer published as of 2026-10-28.",
        ),
    ),
)

ALL_SOURCES = NATIONAL + CASCAIS_SOURCES
