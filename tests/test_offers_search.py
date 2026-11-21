import httpx
import pytest
from fastapi.testclient import TestClient

from adrobot.keitaro import KeitaroClient, get_keitaro_client
from adrobot.main import create_app


@pytest.fixture
def client():
    def tracker(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/admin_api/v1/offers/111":
            return httpx.Response(
                200, json={"id": 111, "name": "Beauty 111", "state": "active"}
            )
        if request.url.path == "/admin_api/v1/offers/99":
            return httpx.Response(
                200, json={"id": 99, "name": "Beauty deleted", "state": "deleted"}
            )
        if request.url.path == "/admin_api/v1/offers/404":
            return httpx.Response(404)
        assert request.url.path == "/admin_api/v1/offers"
        return httpx.Response(
            200,
            json=[
                {"id": 99, "name": "Beauty deleted", "state": "deleted"},
                *[
                    {
                        "id": offer_id,
                        "name": f"Beauty {offer_id}",
                        "state": "active",
                        "notes": "private",
                    }
                    for offer_id in range(100, 111)
                ],
            ],
        )

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app) as client:
            yield client


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("  bEAuTY ", [{"id": i, "name": f"Beauty {i}"} for i in range(100, 110)]),
        ("111", [{"id": 111, "name": "Beauty 111"}]),
        ("99", []),
        ("404", []),
        ("unknown", []),
        (" ", []),
    ],
)
def test_offer_search(client, query, expected):
    response = client.get("/api/offers/search", params={"q": query})
    assert response.status_code == 200
    assert response.json() == expected
