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
from app.api import property as property_api
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
from app.services.property_location import PropertyLocationService

logger = logging.getLogger("habita")


class ConfigurationError(RuntimeError):
    pass


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
            mongo_repo = MongoPropertyRepository(mongo, settings.mongodb_db_name)
            await mongo_repo.ensure_indexes()
            repository = mongo_repo
            permit_repo = MongoPermitRepository(mongo, settings.mongodb_db_name)
            await permit_repo.ensure_indexes()
        elif settings.allow_ephemeral_storage:
            logger.warning("MONGODB_URI not set: properties are kept in memory for this process only.")
            repository = InMemoryPropertyRepository()
            permit_repo = InMemoryPermitRepository()
        else:
            # Never acknowledge saves into memory unless explicitly allowed.
            raise ConfigurationError("MONGODB_URI is required (set ALLOW_EPHEMERAL_STORAGE=true for a local in-memory store).")

        if not settings.google_maps_api_key:
            logger.warning("GOOGLE_MAPS_API_KEY not set: address resolution will return 503.")
        if not settings.meta_api_key:
            logger.warning("META_API_KEY not set: permit intelligence will return 503.")

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
            try:
                yield
            finally:
                maintenance.cancel()
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
