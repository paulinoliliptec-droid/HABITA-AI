"""Explicit tools for the Permit agent.

The model obtains facts only through these tools; HABITA executes them and
returns structured results. Fact-bearing tools also record Evidence (deduplicated
per underlying fact), and their results carry the evidence IDs the model must
cite. Arguments are validated here, never trusted.

HR-003: regulatory evidence comes only from sources the official registry trusts for
the property's jurisdiction chain (curated findings and retrieved official passages),
and carries its provenance. No tool takes a URL, and none can change a source's status.
Planning context comes from the jurisdiction's PlanningContextResolver, never the model.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.schemas.permit import ChecklistItem, Evidence, MissingInput, PermitMatter
from app.schemas.property import ResolvedProperty
from app.schemas.sources import SourceProvenance
from app.services.permit.admissibility import partition
from app.services.permit.repository import PermitRepository
from app.services.permit.requirements import USER_QUESTIONS_PER_ROUND
from app.services.permit.sources.base import SourceRegistry, Topic
from app.services.planning.resolver import PlanningContextService
from app.services.property_location import PropertyLocationService
from app.services.sources.registry import OfficialSourceRegistry
from app.services.sources.retrieval import RegulatoryRetriever

#: Official passages returned per search (in addition to curated findings).
PASSAGES_PER_SEARCH = 3

TOPICS: tuple[Topic, ...] = (
    "licensing_procedure",
    "change_of_use",
    "unit_division",
    "horizontal_property",
    "habitability",
    "land_use_planning",
    "competent_authority",
)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS: list[dict] = [
    _tool("get_property_context", "Resolved address, coordinates and location precision of the property.", {}, []),
    _tool("get_jurisdiction_context", "Administrative hierarchy (country → municipality) governing the property.", {}, []),
    _tool("get_competent_authority", "The authority competent for building permits at the property, with its legal basis.", {}, []),
    _tool("get_available_evidence", "All evidence gathered so far for this matter, including user-supplied information.", {}, []),
    _tool(
        "get_planning_context",
        "The planning instrument and zoning status at the property from official sources, or the official maps "
        "that must be checked when the classification can't be determined automatically.",
        {}, [],
    ),
    _tool(
        "search_regulatory_sources",
        "Search authoritative regulatory sources that apply to the property's jurisdiction.",
        {
            "topics": {"type": "array", "items": {"type": "string", "enum": list(TOPICS)}},
            "query": {"type": "string"},
        },
        ["topics", "query"],
    ),
    _tool(
        "request_missing_information",
        "Ask the user for a fact that only the user can know, for an existing checklist item (item_key). "
        "Facts an authority, an official document or a HABITA tool can provide must not be asked of the user.",
        {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_key": {"type": "string"},
                        "question": {"type": "string"},
                        "reason": {"type": "string"},
                        "owner": {"type": "string", "enum": ["USER", "SYSTEM_TOOL", "AUTHORITY", "DOCUMENT", "UNKNOWN"]},
                    },
                    "required": ["item_key", "question", "reason", "owner"],
                    "additionalProperties": False,
                },
            }
        },
        ["items"],
    ),
]


class ToolError(Exception):
    """A tool call that can't be executed; reported back to the model as a structured error."""


@dataclass
class PermitTools:
    matter: PermitMatter
    repository: PermitRepository
    properties: PropertyLocationService
    sources: SourceRegistry
    #: HR-003: the official source registry (trust), official-text retrieval and planning context.
    official: OfficialSourceRegistry | None = None
    retriever: RegulatoryRetriever | None = None
    planning: PlanningContextService | None = None
    #: The canonical checklist: request_missing_information may only reference these keys.
    checklist: dict[str, ChecklistItem] = field(default_factory=dict)
    _property: ResolvedProperty | None = field(default=None, init=False)
    #: User questions accepted through the tool during this run (canonical keys, user-owned only).
    requested: list[MissingInput] = field(default_factory=list, init=False)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None or name not in {spec["function"]["name"] for spec in TOOL_SPECS}:
            return {"ok": False, "error": f"Unknown tool '{name}'."}
        try:
            return {"ok": True, **(await handler(**arguments))}
        except TypeError:
            return {"ok": False, "error": f"Invalid arguments for '{name}'."}
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}

    # --- context tools ------------------------------------------------------------

    async def property(self) -> ResolvedProperty:
        if self._property is None:
            prop = await self.properties.get(self.matter.property_id)
            if prop is None:
                raise ToolError("The property no longer exists.")
            self._property = prop
        return self._property

    async def jurisdiction_chain(self) -> list[str]:
        return [level.id for level in (await self.property()).jurisdiction.levels]

    async def _tool_get_property_context(self) -> dict[str, Any]:
        prop = await self.property()
        evidence = await self._record(
            source_type="property_record",
            source_title="HABITA property record",
            source_reference=f"{prop.property_id} (Google Maps Geocoding, resolved {prop.resolved_at:%Y-%m-%d})",
            jurisdiction_id=prop.jurisdiction.id,
            claim_supported="Location of the property",
            excerpt=f"{prop.formatted_address} ({prop.precision} precision)",
            structured={"formatted_address": prop.formatted_address, "coordinates": prop.coordinates.model_dump(), "precision": prop.precision},
            confidence="high" if prop.precision in ("rooftop", "interpolated") else "medium",
            verification_status="system_record",
            dedupe_key=f"property:{prop.property_id}:{prop.resolved_at.isoformat()}",
        )
        return {"evidence_id": evidence.evidence_id, "property": evidence.structured}

    async def _tool_get_jurisdiction_context(self) -> dict[str, Any]:
        prop = await self.property()
        j = prop.jurisdiction
        levels = [{"type": lvl.type, "id": lvl.id, "name": lvl.name, "label": lvl.label} for lvl in j.levels]
        evidence = await self._record(
            source_type="jurisdiction_record",
            source_title="HABITA jurisdiction resolution",
            source_reference=f"Jurisdiction {j.id} (HABITA adapter, from Google Maps address components)",
            jurisdiction_id=j.id,
            claim_supported="Administrative hierarchy governing the property",
            excerpt=" → ".join(f"{lvl['label']}: {lvl['name']}" for lvl in levels),
            structured={"jurisdiction_id": j.id, "levels": levels, "coverage": j.coverage},
            confidence="high" if j.coverage == "modelled" else "low",
            verification_status="system_record",
            dedupe_key=f"jurisdiction:{j.id}",
        )
        return {"evidence_id": evidence.evidence_id, "jurisdiction": evidence.structured}

    async def _tool_get_competent_authority(self) -> dict[str, Any]:
        prop = await self.property()
        authority = prop.jurisdiction.local_authority
        if authority is None:
            return {"evidence_id": None, "authority": None, "note": "No competent authority is modelled for this location."}
        basis = "; ".join(" ".join(filter(None, (s.title, s.reference))) for s in authority.sources)
        evidence = await self._record(
            source_type="authority_record",
            source_title=authority.name,
            source_reference=basis or authority.id,
            jurisdiction_id=authority.jurisdiction_id,
            authority_id=authority.id,
            claim_supported="Competent authority for building permits at the property",
            excerpt=f"{authority.name}: {authority.competence}",
            structured=authority.model_dump(),
            confidence="high",
            verification_status="system_record",
            dedupe_key=f"authority:{authority.id}",
        )
        return {"evidence_id": evidence.evidence_id, "authority": authority.model_dump()}

    async def admissible_evidence(self) -> list[Evidence]:
        """The matter's evidence that may be relied on now: history minus records whose source is no
        longer trusted for this jurisdiction (CX-2). Without a registry nothing sourced is admissible."""
        records = await self.repository.list_evidence(self.matter.matter_id)
        chain = await self.jurisdiction_chain()
        trusted = await self.official.trusted_ids(chain) if self.official is not None else set()
        return partition(records, self.matter, chain, trusted)[0]

    async def _tool_get_available_evidence(self) -> dict[str, Any]:
        return {"evidence": compact_evidence(await self.admissible_evidence())}

    async def _tool_get_planning_context(self) -> dict[str, Any]:
        if self.planning is None or self.official is None:
            raise ToolError("Planning context is not available.")
        prop = await self.property()
        context = await self.planning.resolve(prop)
        if context.status == "not_supported" or context.instrument is None:
            return {"evidence_id": None, "planning_context": context.model_dump(mode="json")}
        instrument = await self.official.get(context.instrument.source_id)
        if instrument is None or instrument.status != "trusted":
            return {"evidence_id": None, "planning_context": None, "note": "The planning instrument is not trusted."}
        documents = "; ".join(d.designation or d.title for d in context.documents_to_consult)
        evidence = await self._record(
            source_type="planning_context",
            source_title=f"Planning context — {context.instrument.title}",
            source_reference=" — ".join(filter(None, (context.instrument.version, documents))),
            source_url=context.instrument.official_url,
            jurisdiction_id=context.jurisdiction_id,
            authority_id=context.competent_authority.id if context.competent_authority else None,
            claim_supported="Planning classification of the parcel",
            excerpt=context.guidance,
            structured={**context.model_dump(mode="json"), "authoritative_determination": context.status == "resolved"},
            confidence="high" if context.status == "resolved" else "low",
            verification_status="system_record",
            dedupe_key=f"planning:{prop.property_id}:{context.resolver}:{context.resolver_version}:"
                       f"{context.status}:{context.instrument.version}",
            provenance=SourceProvenance(
                source_id=instrument.source_id, basis="planning_context", trust_status=instrument.status,
                authority_class=instrument.authority_class, official_url=instrument.official_url,
                version=instrument.version, locator=documents or None, retrieved_at=context.source_retrieved_at,
            ),
        )
        return {"evidence_id": evidence.evidence_id, "planning_context": {
            "status": context.status, "instrument": context.instrument.title, "guidance": context.guidance,
            "classification": context.classification.label if context.classification else None,
            "documents_to_consult": [d.designation or d.title for d in context.documents_to_consult],
        }}

    async def _tool_search_regulatory_sources(self, topics: list[str], query: str) -> dict[str, Any]:
        unknown = [t for t in topics if t not in TOPICS]
        if unknown:
            raise ToolError(f"Unknown topics: {unknown}. Allowed: {list(TOPICS)}.")
        if self.official is None:
            raise ToolError("The official source registry is not available.")
        chain = await self.jurisdiction_chain()
        trusted = {s.source_id: s for s in await self.official.trusted(chain)}
        results = []
        for hit in self.sources.search(chain, topics, query):
            src, finding = hit.source, hit.finding
            registered = trusted.get(src.source_id)
            if registered is None:
                continue  # not trusted (or not registered) for this jurisdiction: never evidence
            evidence = await self._record(
                source_type="regulatory_source",
                source_title=src.title,
                source_reference=" — ".join(filter(None, (src.reference, finding.pinpoint))),
                source_url=src.url,
                jurisdiction_id=src.jurisdiction_id,
                authority_id=src.authority_id,
                claim_supported=", ".join(finding.topics),
                excerpt=finding.statement,
                structured={
                    "source_id": src.source_id,
                    "finding_id": finding.finding_id,
                    "issuer": src.issuer,
                    "version_note": src.version_note,
                    "retrieval": src.retrieval,
                    "reviewed_on": src.reviewed_on.isoformat() if src.reviewed_on else None,
                },
                confidence="medium",
                verification_status="curated_reference",
                dedupe_key=f"source:{src.source_id}:{finding.finding_id}",
                provenance=SourceProvenance(
                    source_id=src.source_id, basis="curated_reference", trust_status=registered.status,
                    authority_class=registered.authority_class, official_url=registered.official_url,
                    version=registered.version, locator=finding.pinpoint,
                ),
            )
            results.append(evidence)
        if self.retriever is not None:
            for passage in await self.retriever.search(chain, topics, query, k=PASSAGES_PER_SEARCH):
                src, chunk, snapshot = passage.source, passage.chunk, passage.snapshot
                locator = chunk.locator.label()
                evidence = await self._record(
                    source_type="regulatory_source",
                    source_title=src.title,
                    source_reference=f"{locator} — {src.version or f'retrieved {snapshot.retrieved_at:%Y-%m-%d}'}",
                    source_url=src.official_url,
                    jurisdiction_id=src.jurisdiction_id,
                    authority_id=src.authority_id,
                    claim_supported=", ".join(topics),
                    excerpt=chunk.text[:1500],
                    structured={"source_id": src.source_id, "chunk_id": chunk.chunk_id, "snapshot_id": snapshot.snapshot_id,
                                "locator": chunk.locator.model_dump(), "retrieval": "official_text"},
                    confidence="medium",
                    verification_status="official_text",
                    dedupe_key=f"official:{chunk.chunk_id}",
                    provenance=SourceProvenance(
                        source_id=src.source_id, basis="official_text", trust_status=src.status,
                        authority_class=src.authority_class, official_url=snapshot.final_url, version=src.version,
                        locator=locator, snapshot_id=snapshot.snapshot_id, sha256=snapshot.sha256,
                        retrieved_at=snapshot.retrieved_at,
                    ),
                )
                results.append(evidence)
        return {"jurisdiction_chain": chain, "results": compact_evidence(results)}

    async def _tool_request_missing_information(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        accepted: list[str] = []
        rejected: list[dict[str, str]] = []
        pending = {m.input_key for m in self.matter.missing_inputs} | {m.input_key for m in self.requested}
        for raw in items:
            key = raw.get("item_key") if isinstance(raw, dict) else None
            item = self.checklist.get(key) if isinstance(key, str) else None
            if item is None:
                rejected.append({"item_key": str(key), "reason": "unknown checklist key; use an existing item_key"})
            elif item.owner != "USER" or raw.get("owner") != "USER":
                rejected.append({"item_key": key, "reason": f"not user-owned ({item.owner}); HABITA handles it as a tool "
                                 "lookup or an authority condition, not a question to the user"})
            elif key in self.matter.inputs or key in pending:
                rejected.append({"item_key": key, "reason": "duplicate: already answered or already asked"})
            elif len(accepted) >= USER_QUESTIONS_PER_ROUND:
                rejected.append({"item_key": key, "reason": f"at most {USER_QUESTIONS_PER_ROUND} new questions per round"})
            else:
                question = str(raw.get("question") or item.question).strip()[:300] or item.question
                reason = str(raw.get("reason") or "").strip()[:300] or f"Needed for: {item.question}"
                self.requested.append(MissingInput(input_key=key, question=question, reason=reason))
                pending.add(key)
                accepted.append(key)
        return {"accepted": accepted, "rejected": rejected}

    # --- helpers ------------------------------------------------------------------

    async def _record(self, **fields: Any) -> Evidence:
        return await self.repository.add_evidence(
            Evidence(evidence_id="pending", matter_id=self.matter.matter_id, retrieved_at=datetime.now(UTC), **fields)
        )


def compact_evidence(records: list[Evidence], only: set[str] | None = None) -> list[dict[str, Any]]:
    """A short, stable view of evidence for model prompts (excerpts truncated, no structured payloads)."""
    return [
        {
            "id": e.evidence_id,
            "type": e.source_type,
            "basis": e.verification_status,
            "source": e.source_title[:80],
            "ref": e.source_reference[:120],
            "jurisdiction": e.jurisdiction_id,
            # Official passages need more of their own wording to be read correctly.
            "fact": e.excerpt[:600 if e.verification_status == "official_text" or e.source_type == "planning_context" else 280],
        }
        for e in records
        if only is None or e.evidence_id in only
    ]


def evidence_catalog(records: list[Evidence]) -> str:
    """Compact JSON listing of evidence for model prompts."""
    return json.dumps(compact_evidence(records), ensure_ascii=False)
