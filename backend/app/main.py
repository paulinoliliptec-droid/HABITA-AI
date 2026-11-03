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
from app.api import voice as voice_api
from app.api import aerial as aerial_api
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
from app.db.staging import confinement_problem
from app.integrations.maps.geocoding import GeocodingClient
from app.integrations.maps.static_maps import MemoryDailyUsage, MongoDailyUsage, StaticMapClient
from app.integrations.meta.client import MetaChatModel
from app.integrations.meta.fallback import FallbackChatModel, fallbacks_within_budget
from app.integrations.speech.client import ElevenLabsClient
from app.integrations.translate.client import GoogleTranslateClient
from app.integrations.meta.image import MetaImageEditor
from app.integrations.meta.transcribe import MetaTranscriber
from app.integrations.meta.segment import MetaSegmenter
from app.integrations.orthophotos import OfficialOrthophotoClient
from app.services.concepts.service import Concepts, InMemoryConceptRepository, MongoConceptRepository
from app.services.dictation import Dictation
from app.services.report.copilot import ReportCopilot
from app.services.aerial.service import AerialAnalysis, InMemoryAerialRepository, MongoAerialRepository
from app.services.afford.repository import InMemoryAffordRepository, MongoAffordRepository
from app.services.files.service import InMemoryFileRepository, MatterFiles, MongoFileRepository
from app.services.files.storage import GcsFileStorage, InMemoryFileStorage, UnconfiguredFileStorage
from app.services.permit.repository import InMemoryPermitRepository, MongoPermitRepository, PermitRepository
from app.services.permit.sources.base import SourceRegistry
from app.services.permit.sources.portugal import PortugalSources
from app.services.permit.workflow import PermitWorkflow
from app.services.i18n.translator import Translator
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


async def _require_confined_user(mongo: AsyncMongoClient, db_name: str) -> None:
    """Staging only: the MongoDB user must hold application privileges on ``db_name`` and nothing else
    (``app.db.staging``): no other database, cluster or any-resource grant, no administrative action."""
    status = await mongo.admin.command({"connectionStatus": 1, "showPrivileges": True})
    problem = confinement_problem(status.get("authInfo", {}), db_name)
    if problem:
        raise ConfigurationError(problem)


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
    permit_image_editor=None,
    dictation_transcriber=None,
    aerial_segmenter=None,
    aerial_orthophotos=None,
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
            afford_repo = MongoAffordRepository(mongo, settings.mongodb_db_name)
            concept_repo = MongoConceptRepository(mongo, settings.mongodb_db_name)
            await concept_repo.ensure_indexes()
            file_repo = MongoFileRepository(mongo, settings.mongodb_db_name)
            await file_repo.ensure_indexes()
        elif settings.allow_ephemeral_storage:
            logger.warning("MONGODB_URI not set: properties are kept in memory for this process only.")
            repository = InMemoryPropertyRepository()
            permit_repo = InMemoryPermitRepository()
            source_repo = InMemorySourceRepository()
            file_repo = InMemoryFileRepository()
            afford_repo = InMemoryAffordRepository()
            concept_repo = InMemoryConceptRepository()
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
            app.state.static_maps = StaticMapClient(
                http, settings.maps_static_api_key.get_secret_value() if settings.maps_static_api_key else None,
                timeout_seconds=settings.maps_static_timeout_seconds,
                rate_per_minute=settings.maps_static_rate_per_minute, burst=settings.maps_static_burst,
                daily_limit=settings.maps_static_daily_limit,
                per_location_hourly=settings.maps_static_per_location_hourly, street_view=settings.maps_street_view,
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"]) if mongo is not None
                else MemoryDailyUsage(),
            )
            app.state.translator = Translator(GoogleTranslateClient(
                http, settings.google_translate_api_key.get_secret_value() if settings.google_translate_api_key else None,
                timeout_seconds=settings.translate_timeout_seconds, rate_per_minute=settings.translate_rate_per_minute,
                burst=settings.translate_burst, daily_limit=settings.translate_daily_limit,
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "translate")
                if mongo is not None else MemoryDailyUsage(),
            ))
            app.state.speech = ElevenLabsClient(
                http, settings.elevenlabs_api_key.get_secret_value() if settings.elevenlabs_api_key else None,
                {"en": settings.elevenlabs_voice_en, "pt": settings.elevenlabs_voice_pt},
                model=settings.elevenlabs_model, timeout_seconds=settings.elevenlabs_timeout_seconds,
                rate_per_minute=settings.elevenlabs_rate_per_minute, burst=settings.elevenlabs_burst,
                daily_limit=settings.elevenlabs_daily_limit, cache_bytes=settings.elevenlabs_cache_bytes,
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "speech")
                if mongo is not None else MemoryDailyUsage(),
            )
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
            muse = permit_model or MetaChatModel(
                meta_http,
                api_key=settings.meta_api_key.get_secret_value() if settings.meta_api_key else None,
                base_url=settings.meta_api_base_url,
                model_id=settings.meta_text_model,
                reasoning_effort=settings.meta_reasoning_effort,
            )
            fallback_http = httpx.AsyncClient(timeout=settings.fallback_timeout_seconds, transport=meta_transport)
            fallbacks = [] if permit_model is not None else [
                MetaChatModel(fallback_http, api_key=key.get_secret_value(), base_url=url, model_id=model_id,
                              attempts=1)
                for url, key, model_id in (
                    (settings.modal_model_base_url, settings.modal_model_api_key, settings.modal_model_id),
                    (settings.baseten_model_base_url, settings.baseten_model_api_key, settings.baseten_model_id),
                )
                if url and key and model_id
            ]
            fallbacks = fallbacks_within_budget(fallbacks, settings.meta_timeout_seconds,
                                                settings.fallback_timeout_seconds)
            # Afinamentos: the open-weight protection layer (Modal, then Baseten), only when Muse Spark is down, and
            # only for the permit workflow. Reading the user's photos and plans stays on Muse Spark: it needs vision,
            # and those private files go only where the files notice says.
            reasoning = FallbackChatModel(muse, *fallbacks) if fallbacks else muse
            if fallbacks:
                logger.info("reasoning fallbacks enabled: %s", ", ".join(m.model_id for m in fallbacks))
            if settings.user_files_bucket:
                file_storage = GcsFileStorage(meta_http, settings.user_files_bucket)
            elif settings.allow_ephemeral_storage:
                file_storage = InMemoryFileStorage()
            else:
                logger.warning("USER_FILES_BUCKET not set: adding files will return 503.")
                file_storage = UnconfiguredFileStorage()
            app.state.afford_repo = afford_repo
            app.state.matter_files = MatterFiles(
                file_repo, file_storage, muse,
                limiter=ResolutionLimiter(settings.file_read_rate_per_minute, settings.file_read_burst,
                                          settings.file_read_max_concurrency),
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "file-reads")
                if mongo is not None else MemoryDailyUsage(),
                daily_limit=settings.file_read_daily_limit, per_matter_daily=settings.file_read_per_matter_daily,
            )
            app.state.concepts = Concepts(
                concept_repo, file_storage, app.state.matter_files,
                permit_image_editor or MetaImageEditor(
                    httpx.AsyncClient(timeout=settings.meta_image_timeout_seconds, transport=meta_transport),
                    api_key=settings.meta_api_key.get_secret_value() if settings.meta_api_key else None,
                    base_url=settings.meta_api_base_url, model_id=settings.meta_image_model),
                limiter=ResolutionLimiter(settings.concept_rate_per_minute, settings.concept_burst, 2),
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "concepts")
                if mongo is not None else MemoryDailyUsage(),
                daily_limit=settings.concept_daily_limit, per_matter=settings.concept_per_matter,
            )
            transcribe_http = httpx.AsyncClient(timeout=settings.meta_transcribe_timeout_seconds,
                                                transport=meta_transport)
            app.state.dictation = Dictation(
                dictation_transcriber or MetaTranscriber(
                    transcribe_http,
                    api_key=settings.meta_api_key.get_secret_value() if settings.meta_api_key else None,
                    base_url=settings.meta_api_base_url, model_id=settings.meta_transcribe_model),
                limiter=ResolutionLimiter(settings.dictation_rate_per_minute, settings.dictation_burst, 2),
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "dictation")
                if mongo is not None else MemoryDailyUsage(),
                daily_limit=settings.dictation_daily_limit, per_caller_daily=settings.dictation_per_caller_daily,
                caller_key=settings.meta_api_key.get_secret_value().encode() if settings.meta_api_key else b"",
            )
            app.state.copilot = ReportCopilot(
                reasoning if settings.meta_api_key or permit_model is not None else None,
                limiter=ResolutionLimiter(settings.copilot_rate_per_minute, settings.copilot_burst, 2),
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "copilot")
                if mongo is not None else MemoryDailyUsage(),
                daily_limit=settings.copilot_daily_limit, per_caller_daily=settings.copilot_per_caller_daily,
                caller_key=settings.meta_api_key.get_secret_value().encode() if settings.meta_api_key else b"",
            )
            segment_http = httpx.AsyncClient(timeout=settings.meta_segmentation_timeout_seconds,
                                             transport=meta_transport)
            app.state.aerial = AerialAnalysis(
                MongoAerialRepository(mongo, settings.mongodb_db_name) if mongo is not None
                else InMemoryAerialRepository(),
                file_storage,
                aerial_orthophotos or OfficialOrthophotoClient(http),
                aerial_segmenter or MetaSegmenter(
                    segment_http, api_key=settings.meta_api_key.get_secret_value() if settings.meta_api_key else None,
                    base_url=settings.meta_api_base_url, model_id=settings.meta_segmentation_model),
                limiter=ResolutionLimiter(settings.aerial_rate_per_minute, settings.aerial_burst, 1),
                usage=MongoDailyUsage(mongo[settings.mongodb_db_name]["usage_counters"], "aerial")
                if mongo is not None else MemoryDailyUsage(),
                daily_limit=settings.aerial_daily_limit,
            )
            app.state.permit_workflow = PermitWorkflow(
                repository=permit_repo,
                properties=property_service,
                sources=SourceRegistry([PortugalSources()]),
                official=official,
                retriever=RegulatoryRetriever(official),
                planning=planning,
                model=reasoning,
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
                await fallback_http.aclose()
                await transcribe_http.aclose()
                await segment_http.aclose()
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
        # Every method the site calls: PUT saves HR-011 figures, DELETE removes an HR-010 file.
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        # Authorization carries a permit matter's capability token.
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Retry-After"],
    )
    app.include_router(property_api.router)
    app.include_router(maintenance_api.router)
    app.include_router(permit_api.router)
    app.include_router(planning_api.router)
    app.include_router(report_api.router)
    app.include_router(voice_api.router)
    app.include_router(aerial_api.router)

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
