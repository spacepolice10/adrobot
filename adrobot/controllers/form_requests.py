from urllib.parse import parse_qsl

from fastapi import HTTPException, Request


def require_same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    site = request.headers.get("sec-fetch-site")
    origin = request.headers.get("origin")
    expected = str(request.url.replace(path="", query="", fragment="")).rstrip("/")
    if site not in {"cross-site", "same-site"}:
        if origin is not None:
            if origin == expected:
                return
        elif site == "same-origin" or request.headers.get("referer", "").startswith(
            expected + "/"
        ):
            return
    raise HTTPException(403, "Откройте форму на странице Adrobot.")


async def read_form(
    request: Request, *, max_fields: int, keep_blank_values: bool = False
) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").partition(";")[0]
    if content_type.strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Ожидаются данные HTML-формы.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16_384:
            raise HTTPException(413, "Данные формы слишком длинные.")
        body.extend(chunk)
    return dict(
        parse_qsl(
            body.decode("utf-8"),
            keep_blank_values=keep_blank_values,
            max_num_fields=max_fields,
            errors="strict",
        )
    )
