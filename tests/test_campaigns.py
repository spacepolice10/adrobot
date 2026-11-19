import json

import httpx
from fastapi.testclient import TestClient

from adrobot.campaigns import get_keitaro_client
from adrobot.keitaro import KeitaroClient
from adrobot.main import create_app

PAYLOAD = {
    "name": "Test campaign",
    "domain_id": 1,
    "group_id": 2,
    "traffic_source_id": 3,
}


def test_post_campaign_maps_keitaro_request_and_returns_id():
    def tracker(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/admin_api/v1/campaigns"
        payload = json.loads(request.content)
        assert payload.pop("alias")
        assert payload == {
            **PAYLOAD,
            "group_id": "2",
            "type": "position",
            "state": "disabled",
        }
        return httpx.Response(201, json={"id": 42, "token": "private"})

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app) as client:
            response = client.post("/api/campaigns", json=PAYLOAD)

    assert response.status_code == 201
    assert response.json() == {"id": 42}
