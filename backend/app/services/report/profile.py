"""HR-008 property profile: what is known about the property, who said it and what is not known.

Built only from what the report already rests on, so it adds no fact and no status. Three kinds never mix: only a source
registered as validated or trusted makes an item official; a geocoder or HABITA's own records are observations; a user's
answer stays a declaration. A value of None means not confirmed, and the origin then says where to confirm it.
Declarations come from the matter's evidence, so a public property report has none."""

from collections.abc import Iterable

from app.schemas.permit import Evidence
from app.schemas.property import ResolvedProperty
from app.schemas.report import ProfileItem
from app.schemas.sources import OfficialSourceOut, PlanningContext
from app.services.i18n.translator import msg

_REGISTERED = ("validated", "trusted")
_GEOCODER = msg("Google Maps geocoding")
_RECORD = msg("HABITA jurisdiction record")
_DECLARED = msg("You stated this in this matter")
_CONFIRM = msg("Official maps or the competent authority")
_NO_VERSION = msg("Registered source, no version recorded")
_AREA = msg("Administrative area")
_REVIEWED = msg("Reviewed reference, not a registered source")
_AS_STATED = msg("As stated by you, not verified")
_UNKNOWN_ANSWERS = ("i don't know", "não sei")  # an answer that says nothing about the property is not a value
_PRECISION = {
    "rooftop": msg("Exact address point"), "interpolated": msg("Interpolated along the street"),
    "area_center": msg("Centre of an area"), "approximate": msg("Approximate"),
}


def _observations(prop: ResolvedProperty) -> list[ProfileItem]:
    day, precision = prop.resolved_at.date(), _PRECISION.get(prop.precision)
    j = prop.jurisdiction
    items = [
        ProfileItem(key="address", label=msg("Address"), value=prop.formatted_address, kind="observation",
                    origin=_GEOCODER, as_of=day, precision=precision),
        ProfileItem(key="location", label=msg("Location"), kind="observation", origin=_GEOCODER, as_of=day,
                    value=f"{prop.coordinates.lat:.6f}, {prop.coordinates.lng:.6f}", precision=precision),
    ]
    items += [ProfileItem(key="jurisdiction", label=msg("Municipality"), value=level.name, kind="observation",
                          origin=_RECORD, as_of=day, precision=_AREA) for level in j.levels if level.type == "municipality"]
    if j.local_authority:  # a reviewed reference, not a registered source: it is never an official fact here
        source = next(iter(j.local_authority.sources), None)
        items.append(ProfileItem(key="competent_authority", label=msg("Competent authority"), kind="observation",
                                 value=j.local_authority.name, origin=source.title if source else _RECORD, as_of=day,
                                 url=source.url if source else None, precision=_REVIEWED))
    return items


def _official(context: PlanningContext, sources: Iterable[OfficialSourceOut]) -> list[ProfileItem]:
    registered = {s.source_id: s for s in sources if s.status in _REGISTERED}
    instrument = context.instrument
    source = registered.get(instrument.source_id) if instrument else None
    zoned = source is not None and context.status == "resolved" and context.classification is not None
    fact = {"kind": "official", "origin": source.publisher, "as_of": source.verified_on, "url": source.official_url,
            "precision": source.version or _NO_VERSION} if source else {"kind": "official", "origin": _CONFIRM}
    return [
        ProfileItem(key="planning_instrument", label=msg("Planning instrument"), value=source.title if source else None,
                    **fact),
        ProfileItem(key="zoning", label=msg("Zoning"), value=context.classification.label if zoned else None,
                    **(fact if zoned else {"kind": "official", "origin": _CONFIRM})),
        ProfileItem(key="parcel_boundary", label=msg("Parcel boundary"), value=None, kind="official", origin=_CONFIRM),
    ]


def _declarations(evidence: Iterable[Evidence]) -> list[ProfileItem]:
    seen: dict[tuple[str, str], ProfileItem] = {}
    for e in evidence:
        if e.source_type != "user_statement" or e.verification_status != "user_declared" or not e.excerpt.strip():
            continue
        key = str(e.structured.get("input_key") or e.claim_supported)
        answer = e.excerpt.strip()
        known = answer.casefold() not in _UNKNOWN_ANSWERS
        seen[key, answer.casefold()] = ProfileItem(
            key=key, label=e.source_reference.removeprefix("Answer to: "), value=answer if known else None,
            kind="declaration", origin=_DECLARED if known else _CONFIRM, as_of=e.retrieved_at.date(),
            precision=_AS_STATED if known else None)
    return list(seen.values())


def build_profile(prop: ResolvedProperty, context: PlanningContext, sources: Iterable[OfficialSourceOut],
                  evidence: Iterable[Evidence] = ()) -> list[ProfileItem]:
    items = [*_official(context, sources), *_observations(prop), *_declarations(evidence)]
    values: dict[str, set[str]] = {}
    for item in items:
        if item.value is not None:
            values.setdefault(item.key, set()).add(item.value.strip().casefold())
    # Nothing is chosen: every side of a disagreement stays, marked.
    return [i.model_copy(update={"conflict": len(values.get(i.key, ())) > 1}) for i in items if i.origin]
