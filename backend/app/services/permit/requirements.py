"""Canonical checklist requirements and deterministic reconciliation.

A checklist item is identified by a canonical machine ID defined here, never by
the model. Each requirement declares:

- who owns the missing information (``owner``): only USER-owned items become
  questions; AUTHORITY / DOCUMENT items become conditions the user must confirm
  with the authority; SYSTEM_TOOL items are satisfied by HABITA's own tools;
- which evidence satisfies it (evidence types, regulatory finding IDs, or the
  user's answer for this key);
- which source topics HABITA searches for it.

``reconcile`` computes every item's status from the persisted evidence and the
user's answers. Checklist completion is application state, not model output.
"""

from dataclasses import dataclass

from app.schemas.permit import ChecklistArea, ChecklistItem, Evidence, Owner
from app.services.permit.sources.base import Topic


@dataclass(frozen=True)
class Requirement:
    key: str
    area: ChecklistArea
    question: str
    owner: Owner
    required: bool = True
    source_types: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    search_topics: tuple[Topic, ...] = ()
    #: For AUTHORITY / DOCUMENT items: the condition shown when HABITA can't settle it.
    condition: str | None = None


_JURISDICTION = Requirement(
    "jurisdiction", "jurisdiction", "Which jurisdiction governs the property?", "SYSTEM_TOOL",
    source_types=("jurisdiction_record",),
)
_AUTHORITY = Requirement(
    "competent_authority", "competent_authority", "Which authority is competent for the permit?", "SYSTEM_TOOL",
    source_types=("authority_record",),
)
_PLANNING = Requirement(
    "planning_constraints", "planning_framework", "What does the municipal plan allow on this parcel?", "AUTHORITY",
    finding_ids=("pdm-land-use",), search_topics=("land_use_planning",),
    condition=(
        "Confirm with the competent authority that the parcel's land-use category and urban parameters "
        "in the municipal plan admit an additional dwelling."
    ),
)
_PROCEDURE = Requirement(
    "licensing_procedure", "licensing_procedure", "Which prior-control procedure would the works require?", "SYSTEM_TOOL",
    finding_ids=("rjue-prior-control", "rjue-use", "simplex-reform"),
    search_topics=("licensing_procedure", "change_of_use"),
)

CATALOG: dict[str, tuple[Requirement, ...]] = {
    "unit_conversion": (
        _JURISDICTION,
        _AUTHORITY,
        Requirement(
            "current_licensed_use", "current_use",
            "What is the property's current licensed use (for example, one single-family dwelling)?", "USER",
        ),
        Requirement(
            "intended_use", "intended_use",
            "How would the two units be arranged (floors, approximate areas), and could each have its own "
            "entrance from the street or a shared area?", "USER",
        ),
        Requirement(
            "ownership_status", "current_use",
            "Is the property under a single owner, or already divided into fractions (propriedade horizontal) "
            "with other owners?", "USER",
        ),
        Requirement(
            "unit_conversion", "restrictions", "What legal requirements apply to dividing a property into units?",
            "SYSTEM_TOOL", finding_ids=("cc-1415-autonomous-units", "cc-1416-nullity"),
            search_topics=("unit_division", "horizontal_property"),
        ),
        _PROCEDURE,
        Requirement(
            "habitability", "restrictions", "Which habitability requirements must each new dwelling meet?",
            "SYSTEM_TOOL", finding_ids=("rgeu-habitability",), search_topics=("habitability",),
        ),
        _PLANNING,
        Requirement(
            "required_documents", "required_documents", "Which documents would the application need?", "DOCUMENT",
            required=False,
            condition="Confirm the documents required for the application with the competent authority before applying.",
        ),
    ),
    "general_overview": (_JURISDICTION, _AUTHORITY, _PROCEDURE, _PLANNING),
}

USER_QUESTIONS_PER_ROUND = 3


def requirements_for(intent: str) -> dict[str, Requirement]:
    return {r.key: r for r in CATALOG.get(intent, ())}


def build_checklist_items(intent: str, wording: dict[str, str]) -> list[ChecklistItem]:
    """Canonical items for an intent; the planner may only rephrase questions of existing keys."""
    return [
        ChecklistItem(
            key=r.key, area=r.area, question=wording.get(r.key) or r.question, required=r.required, owner=r.owner,
        )
        for r in CATALOG.get(intent, ())
    ]


def _supporting(req: Requirement, evidence: list[Evidence]) -> list[str]:
    ids = []
    for e in evidence:
        if e.source_type in req.source_types:
            ids.append(e.evidence_id)
        elif req.finding_ids and e.structured.get("finding_id") in req.finding_ids:
            ids.append(e.evidence_id)
        elif req.owner == "USER" and e.source_type == "user_statement" and e.structured.get("input_key") == req.key:
            ids.append(e.evidence_id)
    return ids


def reconcile(intent: str, items: list[ChecklistItem], evidence: list[Evidence]) -> list[ChecklistItem]:
    """Recompute every item's status and evidence from facts. Pure; returns new items."""
    reqs = requirements_for(intent)
    result = []
    for item in items:
        req = reqs.get(item.key)
        if req is None:  # never produced by build_checklist_items; kept for safety
            result.append(item.model_copy(update={"status": "open"}))
            continue
        ids = _supporting(req, evidence)
        if req.owner in ("AUTHORITY", "DOCUMENT"):
            # Sources describe the rule; only the authority can confirm it for this parcel.
            status = "blocked_external"
        elif ids:
            status = "satisfied"
        elif req.owner == "USER":
            status = "needs_input"
        else:
            status = "open"  # SYSTEM_TOOL / UNKNOWN with no evidence: an evidence gap
        result.append(item.model_copy(update={"status": status, "evidence_ids": ids}))
    return result


def conditions_for(intent: str, items: list[ChecklistItem]) -> list[dict[str, str]]:
    reqs = requirements_for(intent)
    return [
        {"item_key": i.key, "text": reqs[i.key].condition or i.question}
        for i in items
        if i.status == "blocked_external" and i.key in reqs
    ]
