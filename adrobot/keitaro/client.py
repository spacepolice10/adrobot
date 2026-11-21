import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request

from adrobot.diagnostics import request_id
from adrobot.settings import Settings

logger = logging.getLogger(__name__)


class KeitaroError(Exception):
    """The tracker could not complete the request."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _extract_validation_detail(response: httpx.Response, api_key: str) -> str:
    if response.status_code not in {400, 406, 422}:
        return ""
    try:
        body = response.json()
    except ValueError:
        content_type = response.headers.get("content-type", "").partition(";")[0]
        body = response.text if content_type.lower() == "text/plain" else None

    messages = []
    errors = body.get("errors", body.get("detail")) if isinstance(body, dict) else body
    if isinstance(errors, dict):
        for field, values in errors.items():
            values = values if isinstance(values, list) else [values]
            messages.extend(
                f"{field}: {value}" for value in values if isinstance(value, str)
            )
    elif isinstance(errors, list):
        for error in errors:
            if isinstance(error, str):
                messages.append(error)
            elif isinstance(error, dict):
                message = error.get("message") or error.get("msg")
                if isinstance(message, str):
                    field = error.get("field")
                    if not isinstance(field, str):
                        loc = error.get("loc")
                        field = str(loc[-1]) if isinstance(loc, list) and loc else ""
                    messages.append(f"{field}: {message}" if field else message)
    elif isinstance(errors, str):
        messages.append(errors)

    if not messages and isinstance(body, dict):
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                messages.append(value)
                break

    detail = "; ".join(messages)
    if api_key:
        detail = detail.replace(api_key, "[скрыто]")
    return " ".join(detail.split())[:350]


class KeitaroClient:
    def __init__(self, http: httpx.Client):
        self.http = http

    def request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        started = monotonic()
        try:
            try:
                response = self.http.request(method, path, json=json)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if method != "GET":
                    raise
                response = self.http.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Keitaro HTTP failure request_id=%s method=%s path=%s status=%d",
                request_id.get(),
                method,
                exc.request.url.path,
                exc.response.status_code,
            )
            detail = _extract_validation_detail(
                exc.response, self.http.headers.get("Api-Key", "")
            )
            message = (
                f"Keitaro: {exc.request.method} {exc.request.url.path} "
                f"вернул HTTP {exc.response.status_code}"
            )
            if detail:
                message += f". {detail}"
            elif exc.response.status_code == 422:
                message += ". Ответ без распознанного описания ошибки."
            raise KeitaroError(
                message,
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning(
                "Keitaro transport failure request_id=%s method=%s path=%s error=%s",
                request_id.get(),
                method,
                path.partition("?")[0],
                type(exc).__name__,
            )
            raise KeitaroError("Could not complete the request to Keitaro") from exc
        finally:
            logger.debug(
                "Keitaro request request_id=%s method=%s path=%s elapsed_ms=%.1f",
                request_id.get(),
                method,
                path.partition("?")[0],
                (monotonic() - started) * 1000,
            )
        return response

    def request_json(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> object:
        response = self.request(method, path, json=json)
        try:
            return response.json()
        except ValueError as exc:
            raise KeitaroError("Keitaro returned an invalid JSON response") from exc


class KeitaroConfigurationError(Exception):
    """The tracker settings are missing or invalid."""


@contextmanager
def open_keitaro_client(settings: Settings | None = None) -> Iterator[KeitaroClient]:
    settings = settings or Settings()
    url = settings.keitaro_url
    key = settings.keitaro_api_key
    if url is None or key is None or not (api_key := key.get_secret_value().strip()):
        raise KeitaroConfigurationError("Keitaro integration is not configured")

    with httpx.Client(
        base_url=f"{str(url).rstrip('/')}/admin_api/v1/",
        headers={"Api-Key": api_key},
        timeout=10.0,
    ) as http:
        yield KeitaroClient(http)


def get_keitaro_client(request: Request) -> KeitaroClient:
    client = request.app.state.keitaro_client
    if client is None:
        raise HTTPException(503, "Keitaro integration is not configured")
    return client


KeitaroDependency = Annotated[KeitaroClient, Depends(get_keitaro_client)]
