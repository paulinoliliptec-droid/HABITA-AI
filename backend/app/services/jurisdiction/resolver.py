from app.services.jurisdiction.adapters.generic import GenericAdapter
from app.services.jurisdiction.adapters.portugal import PortugalAdapter
from app.services.jurisdiction.base import JurisdictionAdapter


class JurisdictionResolver:
    """Picks the adapter for a country, falling back to the generic one."""

    def __init__(
        self,
        adapters: dict[str, JurisdictionAdapter] | None = None,
        fallback: JurisdictionAdapter | None = None,
    ) -> None:
        self._adapters = adapters if adapters is not None else {"PT": PortugalAdapter()}
        self._fallback = fallback or GenericAdapter()

    def adapter_for(self, country_code: str | None) -> JurisdictionAdapter:
        if not country_code:
            return self._fallback
        return self._adapters.get(country_code.upper(), self._fallback)
