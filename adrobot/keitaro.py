import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx


class KeitaroError(Exception):
    """The tracker could not complete the request."""


class KeitaroClient:
    def __init__(self, http: httpx.Client):
        self.http = http

    def request_json(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> object:
        try:
            response = self.http.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KeitaroError(
                f"Keitaro returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise KeitaroError("Could not complete the request to Keitaro") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise KeitaroError("Keitaro returned an invalid JSON response") from exc


class KeitaroConfigurationError(Exception):
    """The tracker settings are missing or invalid."""


@contextmanager
def configured_client() -> Iterator[KeitaroClient]:
    url = os.environ.get("KEITARO_URL", "").strip().rstrip("/")
    api_key = os.environ.get("KEITARO_API_KEY", "").strip()
    if not url or not api_key:
        raise KeitaroConfigurationError("Keitaro integration is not configured")

    try:
        base_url = httpx.URL(f"{url}/admin_api/v1/")
        if base_url.scheme not in {"http", "https"} or not base_url.host:
            raise httpx.InvalidURL("Expected an absolute HTTP(S) URL")
    except httpx.InvalidURL as exc:
        raise KeitaroConfigurationError("Keitaro URL is invalid") from exc

    with httpx.Client(
        base_url=base_url,
        headers={"Api-Key": api_key},
        timeout=10.0,
    ) as http:
        yield KeitaroClient(http)
