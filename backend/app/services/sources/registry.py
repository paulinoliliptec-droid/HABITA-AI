"""The official source registry: which authoritative sources are valid for a jurisdiction.

Sources are seeded from reviewed code (``catalog.py``) and persisted in
``official_sources``. Their status follows one lifecycle:

    candidate → validated → trusted → retired   (retired → candidate to re-review)

- Only ``trusted`` sources produce evidence the Permit agent can cite.
- Discovery (future) may only add ``candidate`` sources.
- ``validated`` means the automatic checks pass (official host, https, verification
  record); promotion to ``trusted`` is an explicit operator action, recorded in
  ``status_history``. No tool exposed to the model can change a status.
- Seeding never overrides a status an operator has changed in the store.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from app.schemas.sources import OfficialSource, SourceSnapshot, SourceStatus, StatusChange

#: Official hosts and the jurisdiction that publishes on them. A source may live on its own
#: jurisdiction's host or on an ancestor's (a municipal act in the national gazette), never on
#: another jurisdiction's or on a commercial/secondary site.
OFFICIAL_HOSTS: dict[str, str] = {
    "www.cascais.pt": "pt/lisboa/cascais",
    "cascais.pt": "pt/lisboa/cascais",
    "geocascais.cascais.pt": "pt/lisboa/cascais",
    "diariodarepublica.pt": "pt",
    "files.diariodarepublica.pt": "pt",
    "www.dgterritorio.gov.pt": "pt",
    "snig.dgterritorio.gov.pt": "pt",
    "dados.gov.pt": "pt",
}

#: Retrieval methods that fetch content and therefore need a verified official URL.
FETCHING = {"http_pdf", "http_html", "wms_getfeatureinfo", "wfs"}

TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"validated", "retired"},
    "validated": {"trusted", "retired"},
    "trusted": {"retired"},
    "retired": {"candidate"},
}


class SourceRegistryError(ValueError):
    pass


def host_jurisdiction(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return None
    return OFFICIAL_HOSTS.get((parts.hostname or "").lower())


def _within(jurisdiction_id: str, ancestor: str) -> bool:
    return jurisdiction_id == ancestor or jurisdiction_id.startswith(ancestor + "/")


def validation_problems(source: OfficialSource) -> list[str]:
    """Automatic checks a source must pass before it can be validated or trusted."""
    problems = []
    if source.official_url is not None:
        host_scope = host_jurisdiction(source.official_url)
        if host_scope is None:
            problems.append("official_url is not https on an allowlisted official host")
        elif not _within(source.jurisdiction_id, host_scope):
            problems.append(f"official host publishes for {host_scope}, not {source.jurisdiction_id}")
    if source.retrieval_method in FETCHING and source.official_url is None:
        problems.append(f"retrieval method {source.retrieval_method} needs a verified official_url")
    if source.machine_readable != (source.retrieval_method in FETCHING):
        problems.append("machine_readable must match the retrieval method")
    if not (source.provenance.verified_on and source.provenance.verified_by):
        problems.append("no verification record (verified_on / verified_by)")
    return problems


class SourceRepository(Protocol):
    async def upsert_seed(self, source: OfficialSource) -> None: ...
    async def insert_source(self, source: OfficialSource) -> bool: ...
    async def get_source(self, source_id: str) -> OfficialSource | None: ...
    async def list_sources(self) -> list[OfficialSource]: ...
    async def set_status(self, source_id: str, change: StatusChange) -> None: ...
    async def set_latest_snapshot(self, source_id: str, snapshot_id: str) -> None: ...
    async def find_snapshot(self, source_id: str, sha256: str) -> SourceSnapshot | None: ...
    async def get_snapshot(self, snapshot_id: str) -> SourceSnapshot | None: ...
    async def save_snapshot(self, snapshot: SourceSnapshot, chunks: list) -> None: ...
    async def list_chunks(self, snapshot_id: str) -> list: ...


@dataclass(frozen=True)
class TrustPin:
    """The registry's trust state for a jurisdiction chain, read once: what the final gate decides on, and what a
    VERIFIED commit is bound to. ``versions`` = {source_id: (status, trust_version)} for every applicable source."""

    versions: dict[str, tuple[str, int]]

    @property
    def trusted_ids(self) -> set[str]:
        return {sid for sid, (status, _) in self.versions.items() if status == "trusted"}

    def audit(self) -> dict[str, str]:
        return {sid: f"{status}@{version}" for sid, (status, version) in sorted(self.versions.items())}


class OfficialSourceRegistry:
    def __init__(self, repository: SourceRepository, seeds: Iterable[OfficialSource] = ()) -> None:
        self._repo = repository
        self._seeds = tuple(seeds)

    @property
    def repository(self) -> SourceRepository:
        return self._repo

    async def seed(self) -> None:
        for source in self._seeds:
            if source.status in ("validated", "trusted") and (problems := validation_problems(source)):
                raise SourceRegistryError(f"seed {source.source_id} fails validation: {problems}")
            await self._repo.upsert_seed(source)

    async def get(self, source_id: str) -> OfficialSource | None:
        return await self._repo.get_source(source_id)

    async def applicable(self, jurisdiction_chain: list[str]) -> list[OfficialSource]:
        """All registered sources (any status) whose jurisdiction is in the property's chain."""
        return [s for s in await self._repo.list_sources() if s.jurisdiction_id in jurisdiction_chain]

    async def trusted(self, jurisdiction_chain: list[str], topics: Iterable[str] = ()) -> list[OfficialSource]:
        wanted = set(topics)
        return [
            s for s in await self.applicable(jurisdiction_chain)
            if s.status == "trusted" and (not wanted or wanted & set(s.regulatory_scope))
        ]

    async def trusted_ids(self, jurisdiction_chain: list[str]) -> set[str]:
        return {s.source_id for s in await self.trusted(jurisdiction_chain)}

    async def pin(self, jurisdiction_chain: list[str]) -> TrustPin:
        """One read of every applicable source's (status, trust_version)."""
        return TrustPin({s.source_id: (s.status, s.trust_version) for s in await self.applicable(jurisdiction_chain)})

    async def register_candidate(self, source: OfficialSource) -> OfficialSource:
        """Entry point for discovered sources: always stored as an unverified candidate."""
        candidate = source.model_copy(update={
            "status": "candidate", "latest_snapshot_id": None, "status_history": [],
            "provenance": source.provenance.model_copy(update={"added_by": "discovery"}),
        })
        if not await self._repo.insert_source(candidate):
            raise SourceRegistryError(f"{source.source_id} is already registered")
        return candidate

    async def change_status(self, source_id: str, to: SourceStatus, *, operator: str, reason: str) -> OfficialSource:
        """Operator action (CLI). Enforces the lifecycle and the validation checks."""
        source = await self._repo.get_source(source_id)
        if source is None:
            raise SourceRegistryError(f"unknown source {source_id}")
        if to not in TRANSITIONS[source.status]:
            raise SourceRegistryError(f"{source.status} → {to} is not allowed")
        if not operator.strip() or not reason.strip():
            raise SourceRegistryError("an operator name and a reason are required")
        if to in ("validated", "trusted") and (problems := validation_problems(source)):
            raise SourceRegistryError(f"{source_id} fails validation: {problems}")
        await self._repo.set_status(
            source_id, StatusChange(status=to, operator=operator.strip(), reason=reason.strip(), at=datetime.now(UTC))
        )
        return (await self._repo.get_source(source_id)) or source
