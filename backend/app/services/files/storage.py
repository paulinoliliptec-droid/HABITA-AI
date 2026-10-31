"""Where the kept copies of users' files live: a private Cloud Storage bucket, or memory for local runs and tests.

The bucket has uniform access, public access prevention and no soft delete, so deleting an object removes it. On
Cloud Run the backend's own service account authenticates through the metadata server; no key is stored."""

import time
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError

_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_API = "https://storage.googleapis.com"
_UNAVAILABLE = "File storage is temporarily unavailable. Please try again."


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class InMemoryFileStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes | None:
        found = self.objects.get(key)
        return found[0] if found else None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class UnconfiguredFileStorage:
    """No bucket configured: nothing is accepted, nothing is lost."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise ServiceNotConfiguredError("Adding files is not configured on this server.")

    async def get(self, key: str) -> bytes | None:
        return None

    async def delete(self, key: str) -> None:
        return None


class GcsFileStorage:
    def __init__(self, http: httpx.AsyncClient, bucket: str) -> None:
        self._http = http
        self._bucket = bucket
        self._token: tuple[str, float] | None = None

    async def _auth(self) -> dict[str, str]:
        if self._token is None or self._token[1] < time.monotonic() + 60:
            try:
                r = await self._http.get(_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
                r.raise_for_status()
                body = r.json()
            except (httpx.HTTPError, ValueError):
                raise UpstreamServiceError(_UNAVAILABLE) from None
            self._token = (body["access_token"], time.monotonic() + float(body.get("expires_in", 300)))
        return {"Authorization": f"Bearer {self._token[0]}"}

    def _object(self, key: str) -> str:
        return f"{_API}/storage/v1/b/{self._bucket}/o/{quote(key, safe='')}"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            r = await self._http.post(f"{_API}/upload/storage/v1/b/{self._bucket}/o",
                                      params={"uploadType": "media", "name": key}, content=data,
                                      headers={**await self._auth(), "Content-Type": content_type})
        except httpx.HTTPError:
            raise UpstreamServiceError(_UNAVAILABLE) from None
        if r.status_code != 200:
            raise UpstreamServiceError(_UNAVAILABLE)

    async def get(self, key: str) -> bytes | None:
        try:
            r = await self._http.get(self._object(key), params={"alt": "media"}, headers=await self._auth())
        except httpx.HTTPError:
            raise UpstreamServiceError(_UNAVAILABLE) from None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise UpstreamServiceError(_UNAVAILABLE)
        return r.content

    async def delete(self, key: str) -> None:
        try:
            r = await self._http.delete(self._object(key), headers=await self._auth())
        except httpx.HTTPError:
            raise UpstreamServiceError(_UNAVAILABLE) from None
        if r.status_code not in (204, 404):
            raise UpstreamServiceError(_UNAVAILABLE)
