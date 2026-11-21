import json

import httpx
import pytest
from fastapi.testclient import TestClient

from adrobot.keitaro import KeitaroClient, get_keitaro_client
from adrobot.main import create_app

PAYLOAD = {"name": "Test campaign", "country_code": "au", "offer_id": 3749}


@pytest.mark.parametrize("offer_status", [201, 406])
@pytest.mark.parametrize("domain_id", [None, 1813])
def test_post_campaign_configures_both_streams_before_activation(
    offer_status, domain_id, monkeypatch
):
    monkeypatch.delenv("KEITARO_CAMPAIGN_DOMAIN", raising=False)
    if domain_id is None:
        monkeypatch.delenv("KEITARO_CAMPAIGN_DOMAIN_ID", raising=False)
        domain_lookup = {
            "/admin_api/v1/domains": [{"id": 1, "name": "https://in.posdk.xyz/"}],
        }
    else:
        monkeypatch.setenv("KEITARO_CAMPAIGN_DOMAIN_ID", str(domain_id))
        domain_lookup = {
            f"/admin_api/v1/domains/{domain_id}": {
                "id": domain_id,
                "name": "kylovoa.com",
                "state": "active",
            },
        }
    requests = []
    lookups = {
        **domain_lookup,
        "/admin_api/v1/groups?type=campaigns": [{"id": 2, "name": "FORTESTS"}],
        "/admin_api/v1/traffic_sources": [{"id": 3, "name": "FORTESTS"}],
    }

    def tracker(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=lookups[request.url.raw_path.decode()])

        assert request.method == "POST"
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        requests.append((path, payload))

        if path.endswith("/campaigns"):
            return httpx.Response(201, json={"id": 42, "token": "private"})
        if path.endswith("/streams") and payload["type"] == "default":
            return httpx.Response(offer_status, json={"id": 52})
        return httpx.Response(200, json={"id": 51})

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            response = client.post("/campaigns", data=PAYLOAD, follow_redirects=False)

    expected_paths = ["/admin_api/v1/campaigns", *["/admin_api/v1/streams"] * 2]
    if offer_status == 201:
        expected_paths.append("/admin_api/v1/campaigns/42/enable")
        assert response.status_code == 303
        assert response.headers["location"] == "/campaigns"
    else:
        assert response.status_code == 502
        assert "Campaign 42" in response.text
        assert response.headers["content-type"].startswith("text/html")
    assert [path for path, _ in requests] == expected_paths

    campaign, google, offer = (payload for _, payload in requests[:3])
    assert campaign.pop("alias")
    assert campaign == {
        "name": PAYLOAD["name"],
        "group_id": "2",
        "domain_id": domain_id or 1,
        "traffic_source_id": 3,
        "type": "position",
        "state": "disabled",
    }
    assert google["campaign_id"] == offer["campaign_id"] == 42
    assert google["position"] < offer["position"]
    assert google["filters"] == [
        {"name": "country", "mode": "accept", "payload": ["AU"]}
    ]
    assert google["action_payload"] == "https://google.com"
    assert offer["schema"] == "landings"
    assert offer["type"] == "default"
    assert offer["action_type"] == "http"
    assert offer["offers"] == [{"offer_id": 3749, "share": 100, "state": "active"}]


def test_get_campaigns_renders_escaped_summary_from_keitaro():
    def tracker(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/admin_api/v1/campaigns"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 42,
                    "name": "<script>Test</script>",
                    "state": "active",
                    "token": "private",
                }
            ],
        )

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            page = client.get("/campaigns")

    assert page.status_code == 200
    assert 'href="/campaigns/new"' in page.text
    assert '<a href="/campaigns/42">&lt;script&gt;Test&lt;/script&gt;</a>' in page.text
    assert "<td>active</td>" in page.text
    assert "private" not in page.text


def test_campaign_page_shows_live_stream_offers():
    data = {
        "campaigns/42": {"id": 42, "name": "<Campaign>", "state": "active"},
        "campaigns/42/streams": [
            {"id": 51, "name": "Google", "schema": "redirect", "offers": []},
            {
                "id": 52,
                "name": "Offer flow",
                "schema": "landings",
                "offers": [
                    {"offer_id": 3749, "share": 70, "state": "active"},
                    {"offer_id": 3717, "share": 30, "state": "disabled"},
                ],
            },
            {"id": 53, "name": "Empty offer flow", "schema": "landings", "offers": []},
        ],
        "offers": [{"id": 3749, "name": "<Offer>"}],
    }

    def tracker(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        path = request.url.path.removeprefix("/admin_api/v1/")
        if path not in data:
            return httpx.Response(404)
        return httpx.Response(200, json=data[path])

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            page = client.get("/campaigns/42")
            missing = client.get("/campaigns/99")

    assert page.status_code == 200
    assert '<h1 class="campaign-title">&lt;Campaign&gt;</h1>' in page.text
    assert '<div class="campaign-actions" role="group"' in page.text
    assert page.text.index('<form class="campaign-add-offer"') < page.text.index(
        'id="stream-52"'
    )
    assert '<select name="stream_id" aria-label="Поток" required>' in page.text
    assert '<h3 id="stream-52">Offer flow (#52)</h3>' in page.text
    assert '<option value="52">Offer flow (#52)</option>' in page.text
    assert '<option value="53">Empty offer flow (#53)</option>' in page.text
    assert '<option value="51">' not in page.text
    assert 'name="offer_id" :value="selectedOffer?.id' in page.text
    assert 'id="stream-51"' not in page.text
    assert 'class="campaign-offer__name">&lt;Offer&gt;</strong>' in page.text
    assert '<span class="campaign-offer__pill">#3749</span>' in page.text
    assert 'class="campaign-offer__pill campaign-offer__share">70%</span>' in page.text
    assert '<span class="campaign-offer__pill">#3717</span>' in page.text
    assert 'class="campaign-offer__pill campaign-offer__share">30%</span>' in page.text
    assert '<span class="campaign-offer__pill">disabled</span>' in page.text
    assert 'class="campaign-offer__name">—</strong>' in page.text
    assert missing.status_code == 404
    assert '<form class="campaign-add-offer"' not in missing.text


def test_new_campaign_page_does_not_require_keitaro(monkeypatch):
    monkeypatch.delenv("KEITARO_URL", raising=False)
    monkeypatch.delenv("KEITARO_API_KEY", raising=False)

    with TestClient(create_app()) as client:
        page = client.get("/campaigns/new")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'method="post" action="/campaigns"' in page.text
    assert 'src="/static/js/offer-picker.js"' in page.text
    assert 'name="offer_id" :value="selectedOffer?.id' in page.text


@pytest.mark.parametrize(
    ("state", "action", "checked"),
    [("active", "disable", "true"), ("disabled", "enable", "false")],
)
def test_campaign_switch_changes_state_in_keitaro(state, action, checked):
    updated_state = "disabled" if action == "disable" else "active"
    changes = []

    def tracker(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/admin_api/v1/")
        if request.method == "POST":
            assert path == f"campaigns/42/{action}"
            changes.append(updated_state)
        if path.endswith("/streams"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={
                "id": 42,
                "name": "Campaign",
                "state": changes[-1] if changes else state,
            },
        )

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            path = f"/campaigns/42/state/{action}"
            page = client.get("/campaigns/42")
            assert f'action="{path}"' in page.text
            assert f'aria-checked="{checked}"' in page.text
            assert '<form class="campaign-add-offer"' in page.text
            assert 'id="offer-query"' in page.text
            assert 'name="stream_id"' not in page.text
            assert 'name="action" value="add"\n            disabled' in page.text
            assert ':disabled="!selectedOffer"' not in page.text
            assert changes == []
            result = client.post(path)

    assert result.status_code == 200
    assert result.history[0].status_code == 303
    assert changes == [updated_state]
    assert f'aria-checked="{str(updated_state == "active").lower()}"' in result.text


@pytest.mark.parametrize(
    ("archive_status", "expected_status"), [(201, 303), (401, 502)]
)
def test_archive_requires_a_post_and_handles_empty_keitaro_response(
    archive_status, expected_status
):
    writes = []

    def tracker(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "DELETE":
            assert path == "/admin_api/v1/campaigns/42"
            writes.append(path)
            return httpx.Response(archive_status)
        assert request.method == "GET"
        if path.endswith("/streams"):
            return httpx.Response(200, json=[])
        assert path == "/admin_api/v1/campaigns/42"
        return httpx.Response(
            200, json={"id": 42, "name": "<Campaign>", "state": "active"}
        )

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            path = "/campaigns/42/archive"
            assert f'href="{path}"' in client.get("/campaigns/42").text

            confirmation = client.get(path)
            assert confirmation.status_code == 200
            assert "&lt;Campaign&gt;" in confirmation.text
            assert 'href="/campaigns/42">Отмена' in confirmation.text
            assert f'method="post" action="{path}"' in confirmation.text

            rejected = client.post(path, headers={"Origin": "https://other.example"})
            assert rejected.status_code == 403
            assert writes == []

            response = client.post(
                path, headers={"Origin": "http://testserver"}, follow_redirects=False
            )

    assert writes == ["/admin_api/v1/campaigns/42"]
    assert response.status_code == expected_status
    if archive_status == 201:
        assert response.headers["location"] == "/campaigns"
    else:
        assert "Не удалось отправить кампанию в архив." in response.text


def test_create_campaign_shows_keitaro_validation_error_without_api_key(monkeypatch):
    monkeypatch.setenv("KEITARO_CAMPAIGN_DOMAIN_ID", "1813")
    api_key = "private-test-api-key"
    lookups = {
        "/admin_api/v1/domains/1813": {"id": 1813, "state": "active"},
        "/admin_api/v1/groups": [{"id": 2, "name": "FORTESTS"}],
        "/admin_api/v1/traffic_sources": [{"id": 3, "name": "FORTESTS"}],
    }

    def tracker(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=lookups[request.url.path])
        assert request.method == "POST"
        assert request.url.path == "/admin_api/v1/campaigns"
        return httpx.Response(
            422, json={"errors": {"name": ["Already exists"], "test": [api_key]}}
        )

    app = create_app()
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        headers={"Api-Key": api_key},
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            response = client.post("/campaigns", data=PAYLOAD)

    assert response.status_code == 502
    assert "POST /admin_api/v1/campaigns вернул HTTP 422" in response.text
    assert "name: Already exists" in response.text
    assert api_key not in response.text
