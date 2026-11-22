import httpx
from fastapi.testclient import TestClient

from adrobot.db import Base, create_database_engine
from adrobot.keitaro import KeitaroClient, get_keitaro_client
from adrobot.main import create_app
from adrobot.mock_keitaro import MOCK_KEY, create_mock_app


def test_app_runs_campaign_and_offer_workflow_against_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("KEITARO_CAMPAIGN_DOMAIN_ID", "1813")
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    engine = create_database_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    headers = {"Api-Key": MOCK_KEY}
    prefix = "/admin_api/v1"
    with TestClient(create_mock_app()) as mock:
        assert mock.get(f"{prefix}/offers").status_code == 401
        assert len(mock.get(f"{prefix}/offers", headers=headers).json()) == 12

        def send(request: httpx.Request) -> httpx.Response:
            response = mock.request(
                request.method,
                request.url.raw_path.decode("ascii"),
                headers=request.headers,
                content=request.content,
            )
            return httpx.Response(
                response.status_code, headers=response.headers, content=response.content
            )

        with httpx.Client(
            base_url=f"http://mock.test{prefix}/",
            headers=headers,
            transport=httpx.MockTransport(send),
        ) as http:
            app = create_app(database_url)
            app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
            with TestClient(app, headers={"Origin": "http://testserver"}) as client:
                initial = client.get("/campaigns/42")
                assert (
                    "Demo campaign" in initial.text and "Demo Offer A" in initial.text
                )
                search = client.get("/api/offers/search", params={"q": "Demo Offer"})
                assert [offer["id"] for offer in search.json()] == list(range(7, 17))
                last = client.get("/api/offers/search", params={"q": "18"})
                assert last.json() == [{"id": 18, "name": "Demo Offer L"}]

                created = client.post(
                    "/campaigns",
                    data={
                        "name": "Mock-only campaign",
                        "country_code": "AU",
                        "offer_id": 7,
                    },
                )
                assert created.status_code == 200
                assert "Mock-only campaign" in created.text
                campaign = mock.get(f"{prefix}/campaigns/43", headers=headers).json()
                assert campaign["state"] == "active"
                streams = mock.get(
                    f"{prefix}/campaigns/43/streams", headers=headers
                ).json()
                google, is_offer_stream = streams
                assert google["filters"][0]["payload"] == ["AU"]
                assert google["action_payload"] == "https://google.com"
                assert is_offer_stream["offers"] == [
                    {"offer_id": 7, "share": 100, "state": "active"}
                ]

                stream_id = is_offer_stream["id"]
                detail = client.get("/campaigns/43")
                assert (
                    f'type="hidden" name="stream_id" value="{stream_id}"' in detail.text
                )
                assert '<select name="stream_id"' not in detail.text
                assert ':disabled="!selectedOffer"' in detail.text
                draft = "/campaigns/43/draft"
                assert client.post(draft, data={"action": "refetch"}).status_code == 200
                edited = client.post(
                    draft, data={"action": "add", "stream_id": stream_id, "offer_id": 8}
                )
                assert "Demo Offer B" in edited.text
                assert edited.text.count(">50%</span>") == 2
                for page in (
                    edited,
                    client.get("/campaigns/43"),
                    client.post(draft, data={"action": "refetch"}),
                ):
                    assert page.text.count("campaign-offer--pending") == 1
                    row = page.text.split("campaign-offer--pending", 1)[1].split(
                        "</li>", 1
                    )[0]
                    assert "Demo Offer B" in row and ">Pending</span>" in row
                remote = mock.get(
                    f"{prefix}/streams/{stream_id}", headers=headers
                ).json()
                assert len(remote["offers"]) == 1

                synced = client.post(draft, data={"action": "sync"})
                assert synced.status_code == 200
                assert "Офферы синхронизированы" in synced.text
                assert "campaign-offer--pending" not in synced.text
                remote = mock.get(
                    f"{prefix}/streams/{stream_id}", headers=headers
                ).json()
                assert remote["offers"] == [
                    {"offer_id": 7, "share": 50, "state": "active"},
                    {"offer_id": 8, "share": 50, "state": "active"},
                ]
                target = {"stream_id": stream_id, "offer_id": 7}
                for action in ("pin", "unpin"):
                    assert (
                        client.post(
                            draft, data={"action": action, **target}
                        ).status_code
                        == 200
                    )
                remote["offers"][0]["share"] = 70
                remote["offers"][1]["share"] = 30
                stream_url = f"{prefix}/streams/{stream_id}"
                assert (
                    mock.put(
                        stream_url, headers=headers, json={"offers": remote["offers"]}
                    ).status_code
                    == 200
                )
                refreshed = client.post(draft, data={"action": "refetch"})
                assert refreshed.status_code == 200
                assert (
                    ">70%</span>" in refreshed.text and ">30%</span>" in refreshed.text
                )
                assert 'value="sync"' not in refreshed.text
                assert client.post(draft, data={"action": "sync"}).status_code == 200
                assert (
                    mock.get(stream_url, headers=headers).json()["offers"]
                    == remote["offers"]
                )
                archived = client.post("/campaigns/43/archive")
                assert archived.status_code == 200
                assert "Mock-only campaign" not in archived.text
