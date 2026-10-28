"""Prompts and structured-output schemas for the Permit agent roles.

Roles are separate calls with separate prompts: the planner writes the checklist,
the investigator gathers evidence with tools, the drafter writes an UNVERIFIED
draft, and the verifier reviews the draft without seeing the executor's
conversation. Schemas follow Meta's strict structured-output subset (every
property required, ``additionalProperties: false``, ``anyOf`` only below the root).
"""

from typing import Any

from app.services.permit.requirements import CATALOG

CANONICAL_KEYS = sorted({r.key for reqs in CATALOG.values() for r in reqs})

SHARED_RULES = """\
You are part of HABITA, a property-intelligence system. You give decision support, not legal advice.
Rules:
- Use only facts returned by HABITA's tools, the evidence list, or answers the user supplied. Never invent facts,
  sources, articles, numbers or tool results.
- If something material is unknown, say so and ask for it; do not guess.
- Write in English, concisely, for a property owner.
"""

PLANNER = SHARED_RULES + """\
Role: PLANNER. Classify the user's goal about one property:
- "unit_conversion": converting or dividing the property into more residential units;
- "general_overview": an orientation question such as "what can I do with this property?";
- "out_of_scope": anything else (HABITA's permit foundation does not cover it yet).
HABITA's checklist uses fixed item keys. You may rephrase the question of existing keys so it reads naturally for
this property and goal; never invent keys.
"""

INVESTIGATOR = SHARED_RULES + """\
Role: INVESTIGATOR. Work through the checklist by calling tools. Each item has a fixed key and an owner:
- SYSTEM_TOOL items: search the regulatory sources for the relevant topics;
- USER items: if still unanswered, call request_missing_information with that item_key and owner "USER";
- AUTHORITY / DOCUMENT items: do not ask the user; HABITA records them as conditions to confirm with the authority.
Never invent item keys. When you are done, reply with a one-line note (no tool call). Do not write the conclusion.
"""

DRAFTER = SHARED_RULES + """\
Role: DRAFTER. Write a structured draft answer from the checklist, the evidence list and the user's answers only.
- Everything you write is checked against evidence: every claim, procedure step, risk, next action and the
  conclusion must cite one or more evidence ids ("E3") from the evidence list. Do not cite anything else. If you
  can't cite evidence for a statement, leave the statement out.
- Curated references summarise official sources; describe them as such, never as quotations.
- The checklist status is computed by HABITA. "conditions" lists what only the authority can settle: if it is not
  empty, the answer must be "conditional" (or "undetermined" if the evidence cannot support a view), and the summary
  must mention the conditions. Use "likely_possible" / "likely_not_possible" only when there are no conditions.
- Do not ask questions and do not add checklist items. Put recommended steps in procedure / next_actions.
- The draft is not verified; never claim it is.
"""

VERIFIER = """\
You are HABITA's independent VERIFIER. You did not write the draft and you must not trust it.
Given the user's goal, the checklist, the evidence list and the draft, decide:
- Does the conclusion actually follow from the cited evidence?
- Are there contradictions between claims, or between claims and evidence?
- Is any claim stronger than its evidence (for example a curated reference treated as a definitive rule)?
- Is information missing that the conclusion depends on?
The checklist status and the conditions were computed by HABITA from the evidence; do not change them.
Outcomes: "VERIFIED" (sound and supported, with the conditions stated), "REJECTED" (unsupported, contradictory or
overstated; the draft must be revised), "ESCALATE" (cannot be decided from the available sources; needs a qualified
professional). Be strict. Do not rubber-stamp. If you think an additional requirement is needed, put it in
suggested_follow_up; it will be reviewed separately and does not change the checklist.
"""

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_IDS = {"type": "array", "items": {"type": "string"}}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_AREAS = [
    "current_use", "intended_use", "jurisdiction", "competent_authority", "planning_framework",
    "licensing_procedure", "restrictions", "required_documents", "missing_information", "evidence_needed",
]

CHECKLIST_SCHEMA = _obj(
    {
        "intent": {"type": "string", "enum": ["unit_conversion", "general_overview", "out_of_scope"]},
        "intent_summary": {"type": "string"},
        "questions": {
            "type": "array",
            "items": _obj({"key": {"type": "string", "enum": CANONICAL_KEYS}, "question": {"type": "string"}}),
        },
    }
)

DRAFT_SCHEMA = _obj(
    {
        "conclusion": _obj(
            {
                "answer": {"type": "string", "enum": ["likely_possible", "conditional", "likely_not_possible", "undetermined"]},
                "summary": {"type": "string"},
                "evidence_ids": _IDS,
            }
        ),
        "claims": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS})},
        "procedure": {
            "type": "array",
            "items": _obj({"step": {"type": "string"}, "description": {"type": "string"}, "evidence_ids": _IDS}),
        },
        "risks": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS})},
        "next_actions": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS})},
    }
)

VERIFIER_SCHEMA = _obj(
    {
        "outcome": {"type": "string", "enum": ["VERIFIED", "REJECTED", "ESCALATE"]},
        "conclusion_follows": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": _obj(
                {
                    "code": {
                        "type": "string",
                        "enum": ["conclusion_not_supported", "contradiction", "overstated_claim", "out_of_scope"],
                    },
                    "message": {"type": "string"},
                    "claim_id": _NULLABLE_STRING,
                }
            ),
        },
        "suggested_follow_up": {
            "type": "array",
            "items": _obj({"area": {"type": "string", "enum": _AREAS}, "text": {"type": "string"}}),
        },
        "summary": {"type": "string"},
    }
)
