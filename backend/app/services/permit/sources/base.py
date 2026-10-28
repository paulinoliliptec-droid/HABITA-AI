"""Regulatory source abstraction.

A provider publishes authoritative sources for one or more jurisdictions. The
workflow asks the registry for sources along the property's jurisdiction chain
(country → region → municipality), so national law and municipal plans both
apply to a municipal property, and nothing from another jurisdiction does.

HR-002 ships curated references for Portugal and Cascais: reviewed summaries of
official instruments with their references and links, not live copies of their
text. ``retrieval`` makes that explicit to the verifier and the UI.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

Topic = Literal[
    "licensing_procedure",
    "change_of_use",
    "unit_division",
    "horizontal_property",
    "habitability",
    "land_use_planning",
    "competent_authority",
]


@dataclass(frozen=True)
class SourceFinding:
    finding_id: str
    statement: str
    topics: tuple[Topic, ...]
    #: Article/section the statement rests on, e.g. "art. 1415.º".
    pinpoint: str | None = None


@dataclass(frozen=True)
class RegulatorySource:
    source_id: str
    title: str
    issuer: str
    jurisdiction_id: str
    reference: str
    url: str | None
    version_note: str
    authoritative: bool
    findings: tuple[SourceFinding, ...]
    authority_id: str | None = None
    retrieval: Literal["curated_reference", "live_text"] = "curated_reference"
    #: When the curated summary was last reviewed against the official source.
    reviewed_on: date | None = None


@dataclass(frozen=True)
class SourceHit:
    source: RegulatorySource
    finding: SourceFinding


class RegulatorySourceProvider(Protocol):
    def sources(self) -> tuple[RegulatorySource, ...]: ...


@dataclass
class SourceRegistry:
    providers: list[RegulatorySourceProvider] = field(default_factory=list)

    def search(self, jurisdiction_chain: list[str], topics: list[str], query: str = "") -> list[SourceHit]:
        """Findings from sources in the property's jurisdiction chain matching any topic (or the query)."""
        words = {w for w in query.lower().split() if len(w) > 3}
        hits = []
        for provider in self.providers:
            for source in provider.sources():
                if source.jurisdiction_id not in jurisdiction_chain:
                    continue
                for finding in source.findings:
                    topical = bool(set(topics) & set(finding.topics))
                    textual = bool(words) and any(w in finding.statement.lower() for w in words)
                    if topical or (not topics and textual):
                        hits.append(SourceHit(source, finding))
        return hits

    def covers(self, jurisdiction_chain: list[str]) -> bool:
        return any(
            source.jurisdiction_id in jurisdiction_chain
            for provider in self.providers
            for source in provider.sources()
        )
