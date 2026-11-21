import pytest
from fastapi.testclient import TestClient

from adrobot.keitaro import get_keitaro_client
from adrobot.main import create_app


@pytest.mark.parametrize(
    "path",
    [
        "/campaigns",
        "/campaigns/42/draft",
        "/campaigns/42/state/enable",
        "/campaigns/42/archive",
    ],
)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
    ],
)
def test_campaign_writes_require_same_origin(path, headers):
    with TestClient(create_app()) as client:
        assert client.post(path, headers=headers).status_code == 403


@pytest.mark.parametrize("path", ["/campaigns", "/campaigns/42/draft"])
@pytest.mark.parametrize(
    ("media_type", "body", "status"),
    [
        ("application/json", b"{}", 415),
        ("application/x-www-form-urlencoded", b"a" * 16385, 413),
        ("application/x-www-form-urlencoded", b"a=1&b=2&c=3&d=4", 422),
        ("application/x-www-form-urlencoded", b"a=%ff", 422),
    ],
)
def test_form_limits(path, media_type, body, status):
    app = create_app()
    app.dependency_overrides[get_keitaro_client] = lambda: None
    with TestClient(app) as client:
        result = client.post(
            path,
            content=body,
            headers={
                "Content-Type": media_type,
                "Referer": "http://testserver/campaigns/new",
            },
        )
    assert result.status_code == status
    assert result.headers["X-Request-ID"]
    if path == "/campaigns":
        assert result.headers["content-type"].startswith("text/html")
