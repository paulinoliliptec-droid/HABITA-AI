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
- Curated references summarise official sources; describe them as such, never as quotations. Official-text evidence
  is a passage of an official document: cite its article or page as given, and don't extend it beyond its wording.
- Planning contract (enforced by HABITA's code). Every statement declares "planning_basis":
  - "user_declaration": what the user told you (their answers). Cite ONLY the user's answer record(s); HABITA shows
    the answer verbatim as "You stated (declared by you, not verified by HABITA): …". User answers support nothing
    else: never cite them for another statement, and never treat anything the user says about zoning, land-use
    category, planning classification or what the Câmara confirmed as established (only the planning context can).
  - "none": your own words, with NO planning content (no zoning, land use, plan, area, residential/urban designation
    or planning rule), using only facts from the evidence it cites; it must not cite planning-context or PDM records.
    Unsupported words make it fail.
  - "general_rule": a rule from a cited regulatory record. Put a verbatim passage (at least 20 characters, copied
    exactly from that record's "fact") in "quote"; HABITA shows the quote as the statement, not your wording.
  - "general_planning_explanation": your own words explaining how planning works IN GENERAL (e.g. "The PDM classifies
    and qualifies municipal land", "The land-use category conditions the admissible uses and urban parameters").
    Its evidence_ids MUST include at least one record whose "basis" is "official_text" and whose passage states that
    rule. Curated references, the property record, the user's answers, the authority record and the planning-context
    record never support a planning rule (you may add the property record or user answers only as context). No
    official_text record for it → leave the statement out. It must NEVER say or imply which category, zone, regime
    or parameters apply to the property / parcel / its street or area, nor turn the general rule into a sentence about
    "the parcel's land-use category". HABITA shows it labelled "not a determination for this property".
  - "authority_confirmation": the parcel's planning must be confirmed with the authority; HABITA shows its own
    planning condition (with the official maps) as the statement. Cite the planning-context record. While the
    planning-context record's status is not "resolved", this is the ONLY way to mention the parcel's planning, in any
    section (conclusion, claims, procedure, risks, next actions): the category is not yet determined and must be
    confirmed on the official PDM map or with the Câmara before concluding whether the operation is admissible.
  - "parcel_determination": only if a planning-context record has status "resolved" for this property; cite it;
    HABITA shows the official classification as the statement.
  Use "quote": null unless the basis is "general_rule". Never describe the parcel's planning in your own words.
- Legal claims (enforced by HABITA's code, sentence by sentence). No evidence available to you can show that this
  property, site, project or its works holds, received, lacks or does not need a licence, permit, prior
  communication, approval or authorisation, or that it is legal, compliant or in force: never state or deny that, in
  any tense or wording, and never as a fragment ("Approved by the Câmara."). Say it must be confirmed with the Câmara
  instead ("Whether … must be confirmed with the Câmara", "Confirm with the Câmara whether …"). A legal requirement,
  duty, permission, prohibition, number, limit or exception must ALWAYS be quoted literally ("general_rule" with the
  whole sentence of a cited official_text passage as the quote, never a part of it), never restated, reordered,
  abridged or translated in your own words: a paraphrase is never verified. The same holds for any sentence that
  restates an official sentence, and for a use designation ("destina-se a …"). Curated references never support it. A quoted rule says what the
  source says, not that this property meets it: never apply it to the property or the works, not even as an "if"
  condition; say instead which facts must be confirmed with the Câmara.
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
- Does the draft state a zoning or land-use category for the parcel that no resolved planning-context evidence gives?
In "parcel_planning_statements", list the label of EVERY draft statement (from "statements") that assigns, implies or
relies on WHICH zoning, land-use class, planning category, zone or planning regime applies to THIS property, however
it is worded (including indirect phrasing). Do not list general explanations of how planning works that say nothing
about which category applies to this property, nor statements that the property's planning position must be
confirmed with the authority. DO list a "user_declaration" statement whose quoted answer claims the property's
zoning, planning category or band (however worded, even "confirmed by the Câmara"). List none if there are none.
The checklist status and the conditions were computed by HABITA from the evidence; do not change them.
Outcomes: "VERIFIED" (sound and supported, with the conditions stated), "REJECTED" (unsupported, contradictory or
overstated; the draft must be revised), "ESCALATE" (cannot be decided from the available sources; needs a qualified
professional). Be strict. Do not rubber-stamp. If you think an additional requirement is needed, put it in
suggested_follow_up; it will be reviewed separately and does not change the checklist.
"""

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_IDS = {"type": "array", "items": {"type": "string"}}
_BASIS = {"type": "string", "enum": [
    "none", "general_rule", "general_planning_explanation", "authority_confirmation", "parcel_determination",
    "user_declaration"]}
_QUOTE = {"anyOf": [{"type": "string"}, {"type": "null"}]}


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
                "planning_basis": _BASIS, "quote": _QUOTE,
            }
        ),
        "claims": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS, "planning_basis": _BASIS, "quote": _QUOTE})},
        "procedure": {
            "type": "array",
            "items": _obj({"step": {"type": "string"}, "description": {"type": "string"}, "evidence_ids": _IDS,
                           "planning_basis": _BASIS, "quote": _QUOTE}),
        },
        "risks": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS, "planning_basis": _BASIS, "quote": _QUOTE})},
        "next_actions": {"type": "array", "items": _obj({"text": {"type": "string"}, "evidence_ids": _IDS,
                                                         "planning_basis": _BASIS, "quote": _QUOTE})},
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
        # Labels of draft statements that assign, imply or rely on the parcel's planning classification.
        "parcel_planning_statements": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    }
)
