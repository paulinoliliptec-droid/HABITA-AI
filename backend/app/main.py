import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo import AsyncMongoClient

from app.api import maintenance as maintenance_api
from app.api import permit as permit_api
from app.api import planning as planning_api
from app.api import property as property_api
from app.api import report as report_api
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.rate_limit import ResolutionLimiter
from app.db.property_repository import (
    InMemoryPropertyRepository,
    MongoPropertyRepository,
    PropertyRepository,
)
from app.integrations.maps.geocoding import GeocodingClient
from app.integrations.meta.client import MetaChatModel
from app.services.permit.repository import InMemoryPermitRepository, MongoPermitRepository, PermitRepository
from app.services.permit.sources.base import SourceRegistry
from app.services.permit.sources.portugal import PortugalSources
from app.services.permit.workflow import PermitWorkflow
from app.services.jurisdiction import JurisdictionResolver
from app.services.permit.model import ReasoningModel
from app.services.planning.cascais import cascais_resolver
from app.services.planning.resolver import PlanningContextService
from app.services.property_location import PropertyLocationService
from app.services.sources.catalog import ALL_SOURCES
from app.services.sources.fetcher import SafeFetcher
from app.services.sources.ingest import SourceIngestor
from app.services.sources.registry import OFFICIAL_HOSTS, OfficialSourceRegistry
from app.services.sources.repository import InMemorySourceRepository, MongoSourceRepository
from app.services.sources.retrieval import RegulatoryRetriever

logger = logging.getLogger("habita")


class ConfigurationError(RuntimeError):
    pass


# What dbAdmin/dbOwner add to readWrite (identical on MongoDB 7.0 and 8.0.34, the Atlas cluster's version). collMod can replace the MU-9 validator and
# bypassDocumentValidation skips it: in staging only the migration user (apply-validator) may change it; the rest
# administers users, roles or the database.
_STAGING_FORBIDDEN_ACTIONS = frozenset({
    "analyze", "bypassDocumentValidation", "changeCustomData", "changePassword", "collMod", "compact",
    "configureQueryAnalyzer",
    "createRole", "createUser", "dropDatabase", "dropRole", "dropUser", "enableProfiler", "grantRole",
    "planCacheIndexFilter", "planCacheWrite", "reIndex", "revokeRole", "setAuthenticationRestriction", "storageDetails",
    "validate", "viewRole", "viewUser",
})  # fmt: skip


async def _require_confined_user(mongo: AsyncMongoClient, db_name: str) -> None:
    """Staging only: the MongoDB user must hold application privileges on ``db_name`` and nothing else.

    A separate secret does not prove separate credentials; this refuses to start if the URI's user could also
    reach another database (e.g. the preview's ``habita_ai``), a whole cluster or any resource, or holds
    administrative actions (as with dbOwner).
    """
    status = await mongo.admin.command({"connectionStatus": 1, "showPrivileges": True})
    auth = status.get("authInfo", {})
    if not auth.get("authenticatedUsers"):
        raise ConfigurationError(f"Staging needs an authenticated MongoDB user limited to {db_name}.")
    # A privilege without a "db" is a cluster or anyResource grant; "" means every database.
    reach = {
        str(privilege.get("resource", {}).get("db", "<cluster or any resource>"))
        for privilege in auth.get("authenticatedUserPrivileges", [])
    }
    if reach != {db_name}:
        raise ConfigurationError(f"Staging MongoDB user must be limited to {db_name}; it reaches {sorted(reach)}.")
    admin = {a for privilege in auth["authenticatedUserPrivileges"] for a in privilege.get("actions", [])}
    admin &= _STAGING_FORBIDDEN_ACTIONS
    if admin:
        raise ConfigurationError(f"Staging MongoDB user on {db_name} must not hold administrative actions: {sorted(admin)}.")


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO; Google API keys are query parameters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _maintain_periodically(repository: PropertyRepository, interval_hours: float) -> None:
    """Best-effort background maintenance: at startup, then every interval while running.

    Purges expired Google-derived fields and completes interrupted merges. Cloud Run
    instances scale to zero, so a dormant service runs this on its next start; a fixed
    schedule can call POST /internal/maintenance/run. Failures are logged and retried
    next round; they never affect request handling.
    """
    while True:
        try:
            purged = await repository.purge_expired()
            resumed = await repository.resume_pending_merges()
            if purged or resumed:
                logger.info("Maintenance: purged %d expired snapshots, resumed %d merges", purged, resumed)
        except Exception as exc:
            logger.warning("Maintenance failed: %s", type(exc).__name__)
        await asyncio.sleep(interval_hours * 3600)


async def _ingest_sources_once(ingestor: SourceIngestor) -> None:
    try:
        for report in await ingestor.ingest_jurisdiction("pt/lisboa/cascais"):
            logger.info("Source ingestion: %s %s %s", report.source_id, report.outcome, report.detail)
    except Exception as exc:
        logger.warning("Source ingestion failed: %s", type(exc).__name__)


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
    meta_transport: httpx.AsyncBaseTransport | None = None,
    permit_model: ReasoningModel | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        mongo: AsyncMongoClient | None = None
        repository: PropertyRepository
        if settings.mongodb_uri:
            mongo = AsyncMongoClient(
                settings.mongodb_uri.get_secret_value(),
                serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
                timeoutMS=settings.mongodb_timeout_ms,
                tz_aware=True,
            )
            if settings.app_env == "staging":
                await _require_confined_user(mongo, settings.mongodb_db_name)
            mongo_repo = MongoPropertyRepository(mongo, settings.mongodb_db_name)
            await mongo_repo.ensure_indexes()
            repository = mongo_repo
            permit_repo = MongoPermitRepository(mongo, settings.mongodb_db_name)
            await permit_repo.ensure_indexes()
            source_repo = MongoSourceRepository(mongo, settings.mongodb_db_name)
            await source_repo.ensure_indexes()
        elif settings.allow_ephemeral_storage:
            logger.warning("MONGODB_URI not set: properties are kept in memory for this process only.")
            repository = InMemoryPropertyRepository()
            permit_repo = InMemoryPermitRepository()
            source_repo = InMemorySourceRepository()
        else:
            # Never acknowledge saves into memory unless explicitly allowed.
            raise ConfigurationError("MONGODB_URI is required (set ALLOW_EPHEMERAL_STORAGE=true for a local in-memory store).")

        if not settings.google_maps_api_key:
            logger.warning("GOOGLE_MAPS_API_KEY not set: address resolution will return 503.")
        if not settings.meta_api_key:
            logger.warning("META_API_KEY not set: permit intelligence will return 503.")

        official = OfficialSourceRegistry(source_repo, ALL_SOURCES)
        await official.seed()
        planning = PlanningContextService([cascais_resolver(official)])
        app.state.official_sources = official
        app.state.planning = planning

        async with httpx.AsyncClient(
            timeout=settings.geocoding_timeout_seconds, transport=http_transport
        ) as http:
            api_key = settings.google_maps_api_key.get_secret_value() if settings.google_maps_api_key else None
            app.state.repository = repository
            app.state.settings = settings
            app.state.property_service = property_service = PropertyLocationService(
                geocoder=GeocodingClient(http, api_key),
                resolver=JurisdictionResolver(),
                repository=repository,
                default_language=settings.geocoding_default_language,
                snapshot_ttl=timedelta(days=settings.provider_snapshot_ttl_days),
                limiter=ResolutionLimiter(
                    settings.resolve_rate_per_minute, settings.resolve_burst, settings.resolve_max_concurrency
                ),
            )
            meta_http = httpx.AsyncClient(timeout=settings.meta_timeout_seconds, transport=meta_transport)
            app.state.permit_workflow = PermitWorkflow(
                repository=permit_repo,
                properties=property_service,
                sources=SourceRegistry([PortugalSources()]),
                official=official,
                retriever=RegulatoryRetriever(official),
                planning=planning,
                model=permit_model
                or MetaChatModel(
                    meta_http,
                    api_key=settings.meta_api_key.get_secret_value() if settings.meta_api_key else None,
                    base_url=settings.meta_api_base_url,
                    model_id=settings.meta_text_model,
                    reasoning_effort=settings.meta_reasoning_effort,
                ),
                limiter=ResolutionLimiter(
                    settings.permit_rate_per_minute, settings.permit_burst, settings.permit_max_concurrency
                ),
            )
            maintenance = asyncio.create_task(_maintain_periodically(repository, settings.snapshot_purge_interval_hours))
            ingestion = None
            if settings.source_ingest_on_startup:
                fetcher = SafeFetcher(OFFICIAL_HOSTS, timeout_seconds=settings.source_fetch_timeout_seconds)
                ingestion = asyncio.create_task(_ingest_sources_once(SourceIngestor(official, fetcher)))
            try:
                yield
            finally:
                maintenance.cancel()
                if ingestion is not None:
                    ingestion.cancel()
                await meta_http.aclose()
                if mongo is not None:
                    await mongo.close()

    _configure_logging()
    app = FastAPI(title="HABITA AI", version="0.2.0", lifespan=lifespan)
    # Error handling first, CORS last: the last-added middleware is outermost, so even
    # unexpected errors leave with allowed-origin headers.
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        # Authorization carries a permit matter's capability token.
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Retry-After"],
    )
    app.include_router(property_api.router)
    app.include_router(maintenance_api.router)
    app.include_router(permit_api.router)
    app.include_router(planning_api.router)
    app.include_router(report_api.router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def ready(request: Request) -> dict[str, str]:
        """Readiness: required storage is reachable (structured 503 otherwise)."""
        await request.app.state.repository.ping()
        return {"status": "ready"}

    return app


app = create_app()
