"""Verification protocols and the persisted floor (HR-003 MU-9, M8: rollback must not restore an unsafe verifier).

Every report records the protocol that produced it. ``statement-v1`` is the verifier up to ``98af6af``; it is known
unsafe (it certified licence and approval claims about the property from generic sources), so a VERIFIED report
from it is never committed again, and the reports it already committed are flagged as superseded.

Two guards, independent of which code is deployed:

- ``commit_verified`` reads the floor inside its transaction and refuses a report whose protocol is below it or
  known unsafe. Without a stored floor, ``DEFAULT_FLOOR`` applies (fail closed).
- The ``permit_verifications`` collection gets a server-side validator (``validator``): a VERIFIED document must
  carry an admitted ``protocol`` and its ``claim_atoms``. Code from before MU-9 writes neither, so after a rollback
  its VERIFIED insert fails inside the transaction and nothing is committed.

The floor only moves up (``raise_floor``); there is no command to lower it.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Weakest first.
PROTOCOLS = ("statement-v1", "atomic-v1")
CURRENT = "atomic-v1"
FLOOR_ID = "floor"


class FloorError(ValueError):
    """A floor change that would lower the floor, forget a known-unsafe protocol, or name an unknown protocol."""


def rank(protocol: str) -> int:
    return PROTOCOLS.index(protocol) if protocol in PROTOCOLS else -1


@dataclass(frozen=True)
class Floor:
    min_protocol: str
    known_unsafe: tuple[str, ...] = ()
    history: tuple[dict, ...] = field(default=(), compare=False)

    @classmethod
    def from_doc(cls, doc: dict | None) -> "Floor":
        if not doc:
            return DEFAULT_FLOOR
        return cls(doc["min_protocol"], tuple(doc.get("known_unsafe", ())), tuple(doc.get("history", ())))

    def to_doc(self) -> dict:
        return {"_id": FLOOR_ID, "min_protocol": self.min_protocol, "known_unsafe": list(self.known_unsafe),
                "history": list(self.history)}

    def admitted(self) -> list[str]:
        return [p for p in PROTOCOLS if rank(p) >= rank(self.min_protocol) and p not in self.known_unsafe]

    def admits(self, protocol: str) -> bool:
        return protocol in self.admitted()


DEFAULT_FLOOR = Floor(CURRENT, ("statement-v1",))


def raise_floor(current: Floor, min_protocol: str, operator: str, reason: str,
                known_unsafe: tuple[str, ...] = ()) -> Floor:
    """The new floor, or ``FloorError``: it never goes down and never forgets a known-unsafe protocol."""
    if rank(min_protocol) < 0 or any(rank(p) < 0 for p in known_unsafe):
        raise FloorError(f"Unknown protocol; known: {', '.join(PROTOCOLS)}.")
    if rank(min_protocol) < rank(current.min_protocol):
        raise FloorError(f"The floor is {current.min_protocol}; it can't be lowered to {min_protocol}.")
    if not operator.strip() or not reason.strip():
        raise FloorError("A floor change needs an operator and a reason.")
    unsafe = tuple(dict.fromkeys((*current.known_unsafe, *known_unsafe)))
    if min_protocol in unsafe:
        raise FloorError(f"{min_protocol} is known unsafe.")
    entry = {"at": datetime.now(UTC).isoformat(), "operator": operator, "reason": reason,
             "from": current.min_protocol, "to": min_protocol, "known_unsafe": list(unsafe)}
    return Floor(min_protocol, unsafe, (*current.history, entry))


def validator(floor: Floor) -> dict:
    """Server-side rule for ``permit_verifications``: VERIFIED only with an admitted protocol and its atoms."""
    return {"$or": [
        {"outcome": {"$ne": "VERIFIED"}},
        {"protocol": {"$in": floor.admitted()}, "claim_atoms": {"$type": "array"}},
    ]}
