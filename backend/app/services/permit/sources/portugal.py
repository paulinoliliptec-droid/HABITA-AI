"""Curated regulatory references: Portugal (national) and Cascais (municipal).

Each entry was reviewed on 2026-10-27 against public references. Statements are
deliberately conservative summaries; the UI labels them as references to check
against the official text, and the verifier never treats them as live quotes.
Add a source here (or a new provider module) to extend coverage; no workflow
code changes are needed.
"""

from datetime import date

from app.services.jurisdiction.adapters.portugal import RJUE_COMPETENCE
from app.services.permit.sources.base import RegulatorySource, SourceFinding

REVIEWED = date(2026, 10, 27)
CASCAIS = "pt/lisboa/cascais"

RJUE = RegulatorySource(
    source_id="pt-rjue",
    title="Regime Jurídico da Urbanização e da Edificação (RJUE)",
    issuer="República Portuguesa",
    jurisdiction_id="pt",
    reference="Decreto-Lei n.º 555/99, de 16 de dezembro (consolidated version)",
    url="https://diariodarepublica.pt/dr/detalhe/decreto-lei/555-1999-655682",
    version_note="Amended many times; most recently reformed by the Simplex Urbanístico (Decreto-Lei n.º 10/2024).",
    authoritative=True,
    reviewed_on=REVIEWED,
    findings=(
        SourceFinding(
            finding_id="rjue-prior-control",
            statement=(
                "Urban operations, including building works and alterations, are subject to municipal prior "
                "control under the RJUE (licence or prior communication, depending on the operation)."
            ),
            topics=("licensing_procedure", "unit_division"),
            pinpoint="art. 4.º",
        ),
        SourceFinding(
            finding_id="rjue-competence",
            statement=(
                "The câmara municipal is the body competent to decide on the licensing of urban operations, "
                "with the power to delegate to its president."
            ),
            topics=("competent_authority", "licensing_procedure"),
            pinpoint=RJUE_COMPETENCE.reference,
        ),
        SourceFinding(
            finding_id="rjue-use",
            statement=(
                "The use of buildings or their units, and changes to that use, are regulated by the RJUE; the "
                "applicable procedure for a change of use must be confirmed against the version in force after "
                "the Simplex Urbanístico."
            ),
            topics=("change_of_use", "licensing_procedure"),
            pinpoint="art. 4.º (as amended)",
        ),
    ),
)

SIMPLEX = RegulatorySource(
    source_id="pt-simplex-urbanistico",
    title="Simplex Urbanístico — reform of urban licensing",
    issuer="República Portuguesa",
    jurisdiction_id="pt",
    reference="Decreto-Lei n.º 10/2024, de 8 de janeiro",
    url=None,
    version_note="Phased entry into force during 2024; amended the RJUE and the RGEU.",
    authoritative=True,
    reviewed_on=REVIEWED,
    findings=(
        SourceFinding(
            finding_id="simplex-reform",
            statement=(
                "Decreto-Lei n.º 10/2024 reformed urban licensing procedures, amending the RJUE and the RGEU; "
                "procedures must be read in their post-2024 wording."
            ),
            topics=("licensing_procedure", "change_of_use"),
        ),
    ),
)

CIVIL_CODE_PH = RegulatorySource(
    source_id="pt-codigo-civil-propriedade-horizontal",
    title="Código Civil — propriedade horizontal",
    issuer="República Portuguesa",
    jurisdiction_id="pt",
    reference="Código Civil (Decreto-Lei n.º 47 344, de 25 de novembro de 1966), arts. 1414.º–1438.º-A",
    url=None,
    version_note="Consolidated text in force.",
    authoritative=True,
    reviewed_on=REVIEWED,
    findings=(
        SourceFinding(
            finding_id="cc-1415-autonomous-units",
            statement=(
                "Only autonomous units can be the object of horizontal property: units that are independent, "
                "distinct and isolated from each other, with their own exit to a common part of the building "
                "or to the public way."
            ),
            topics=("unit_division", "horizontal_property"),
            pinpoint="art. 1415.º",
        ),
        SourceFinding(
            finding_id="cc-1416-nullity",
            statement=(
                "If the legal requirements are missing, the title constituting the horizontal property is null "
                "and the building is subject to co-ownership instead."
            ),
            topics=("horizontal_property", "unit_division"),
            pinpoint="art. 1416.º",
        ),
    ),
)

RGEU = RegulatorySource(
    source_id="pt-rgeu",
    title="Regulamento Geral das Edificações Urbanas (RGEU)",
    issuer="República Portuguesa",
    jurisdiction_id="pt",
    reference="Decreto-Lei n.º 38 382, de 7 de agosto de 1951",
    url=None,
    version_note="Amended, including by Decreto-Lei n.º 10/2024.",
    authoritative=True,
    reviewed_on=REVIEWED,
    findings=(
        SourceFinding(
            finding_id="rgeu-habitability",
            statement=(
                "Dwellings must meet the RGEU's general habitability requirements (such as minimum areas, "
                "ceiling heights, natural light and ventilation); each new dwelling created by a division "
                "has to satisfy them on its own."
            ),
            topics=("habitability", "unit_division"),
        ),
    ),
)

PDM_CASCAIS = RegulatorySource(
    source_id="cascais-pdm",
    title="Plano Diretor Municipal de Cascais (PDM-Cascais) — Regulamento",
    issuer="Câmara Municipal de Cascais",
    jurisdiction_id=CASCAIS,
    authority_id=f"{CASCAIS}:camara-municipal",
    reference="PDM-Cascais (2015 revision), latest alteration Aviso n.º 20120/2023, corrected by Aviso n.º 15687/2024/2",
    url="https://www.cascais.pt/sites/default/files/anexos/gerais/new/anexo_6_regulamento_pdm_cascais.pdf",
    version_note="Check the municipality's PDM page for the version in force.",
    authoritative=True,
    reviewed_on=REVIEWED,
    findings=(
        SourceFinding(
            finding_id="pdm-land-use",
            statement=(
                "The PDM classifies and qualifies municipal land; the land-use category of the parcel, shown on "
                "the planning map (planta de ordenamento), determines admissible uses and urban parameters, which "
                "must be checked for the specific parcel before adding a dwelling."
            ),
            topics=("land_use_planning", "unit_division", "change_of_use"),
        ),
    ),
)


class PortugalSources:
    """National Portuguese sources plus the Cascais municipal plan."""

    def sources(self) -> tuple[RegulatorySource, ...]:
        return (RJUE, SIMPLEX, CIVIL_CODE_PH, RGEU, PDM_CASCAIS)
