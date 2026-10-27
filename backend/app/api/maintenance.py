"""Operational endpoint for scheduled maintenance (e.g. Cloud Scheduler).

Disabled (404) unless MAINTENANCE_TOKEN is configured; callers send it in the
``X-Maintenance-Token`` header. Not exposed through CORS: server-to-server only.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, Request

from app.core.errors import NotFoundError, UnauthorizedError

router = APIRouter(prefix="/internal/maintenance", tags=["ops"], include_in_schema=False)


@router.post("/run")
async def run_maintenance(
    request: Request,
    x_maintenance_token: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    token = request.app.state.settings.maintenance_token
    if token is None:
        raise NotFoundError("Not found.")
    if not x_maintenance_token or not hmac.compare_digest(x_maintenance_token, token.get_secret_value()):
        raise UnauthorizedError("Invalid maintenance token.")
    repository = request.app.state.repository
    return {
        "purged": await repository.purge_expired(),
        "merges_resumed": await repository.resume_pending_merges(),
    }
