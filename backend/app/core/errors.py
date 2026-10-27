"""Application errors and their structured HTTP representation.

Every error response has the shape ``{"error": {"code": str, "message": str}}``
so the frontend can branch on ``code`` without parsing messages. This includes
unexpected failures, which are converted inside the CORS middleware so the
browser still receives allowed-origin headers.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class AddressNotFoundError(AppError):
    status_code = 422
    code = "address_not_found"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceNotConfiguredError(AppError):
    status_code = 503
    code = "service_not_configured"


class StorageUnavailableError(AppError):
    status_code = 503
    code = "storage_unavailable"


class UpstreamServiceError(AppError):
    status_code = 502
    code = "upstream_error"


def _error_body(code: str, message: str, **extra: object) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_error_body(exc.code, exc.message), headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "The request is invalid.", details=details),
        )

    # Starlette's default 500 handler runs outside CORSMiddleware, so a browser would see
    # an opaque CORS failure. Catch unexpected errors here, inside it. Register this
    # before CORSMiddleware so CORS stays the outer layer.
    @app.middleware("http")
    async def unexpected_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Type only: exception text from drivers/HTTP clients can contain URLs or URIs.
            logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content=_error_body("internal_error", "Something went wrong on our side. Please try again."),
            )
