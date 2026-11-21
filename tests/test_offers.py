import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adrobot.db import Base, create_database_engine
from adrobot.keitaro import KeitaroClient, get_keitaro_client
from adrobot.main import create_app
from adrobot.models.offer_draft import (
    CampaignOfferDraft,
    DraftOffer,
    DraftSnapshot,
    DraftStream,
)


def test_single_offer_workflow_preserves_draft_across_refetch(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'drafts.db'}"
    engine = create_database_engine(database_url)
    published = [{"offer_id": 7, "share": 100, "state": "active"}]
    offer = {"id": 7, "name": "Test offer", "state": "active"}

    def tracker(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        path = request.url.path.removeprefix("/admin_api/v1/")
        payload = {
            "campaigns/42": {"id": 42, "name": "Campaign", "state": "active"},
            "campaigns/42/streams": [
                {"id": 51, "name": "Google", "schema": "redirect", "offers": []},
                {"id": 52, "name": "Offer", "schema": "landings", "offers": published},
                {"id": 53, "name": "Empty", "schema": "landings", "offers": []},
            ],
            "offers": [offer],
            "offers/7": offer,
        }
        return httpx.Response(200, json=payload[path])

    app = create_app(database_url)
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as tracker_client:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(
            tracker_client
        )
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            path = "/campaigns/42/draft"
            target = {"offer_id": 7, "stream_id": 52}
            page = client.get("/campaigns/42")
            assert 'value="refetch" disabled' in page.text
            toolbar = page.text.split('class="campaign-actions"', 1)[1].split(
                "</div>", 1
            )[0]
            assert 'value="refetch" disabled' in toolbar
            assert "alembic upgrade" not in page.text

            Base.metadata.create_all(engine)
            page = client.get("/campaigns/42")
            assert 'value="refetch"' in page.text
            assert 'value="refetch" disabled' not in page.text

            initial = client.post(path, data={"action": "refetch"})
            assert 'id="campaign-offers-heading">Офферы</h2>' in initial.text
            assert initial.text.index(
                'class="campaign-offers-heading"'
            ) < initial.text.index('<form class="campaign-add-offer"')
            assert "100%" in initial.text
            assert 'class="icon icon--push-pin"' in initial.text
            assert 'class="campaign-sync"' not in initial.text
            pinned = client.post(path, data={"action": "pin", **target})
            assert 'value="unpin"' in pinned.text
            assert "campaign-offer__pin--active" in pinned.text
            assert "icon--push-pin-slash" in pinned.text
            assert "active · Закреплён" not in pinned.text
            assert 'class="campaign-sync"' not in pinned.text
            removed = client.post(path, data={"action": "remove", **target})
            assert "Removed" in removed.text
            assert "campaign-offer__pill--removed" in removed.text
            refetched = client.post(path, data={"action": "refetch"})
            assert "Removed" in refetched.text

            published.clear()
            refreshed = client.post(path, data={"action": "refetch"})
            assert "Removed" in refreshed.text and "Test offer" in refreshed.text
            restored = client.post(path, data={"action": "restore", **target})
            assert 'value="unpin"' in restored.text
            assert "100%" in restored.text
            again = client.post(path, data={"action": "refetch"})
            assert 'value="unpin"' in again.text
            unpinned = client.post(path, data={"action": "unpin", **target})
            assert unpinned.status_code == 200
            assert 'value="pin"' in unpinned.text
            assert 'value="unpin"' not in unpinned.text
            added = client.post(
                path, data={"action": "add", "offer_id": 7, "stream_id": 53}
            )
            assert '<h3 id="stream-53">Empty (#53)</h3>' in added.text
            duplicate = client.post(
                path, data={"action": "add", "offer_id": 7, "stream_id": 53}
            )
            assert duplicate.status_code == 409

    with Session(engine) as db:
        snapshot = db.get(CampaignOfferDraft, 42).snapshot
        assert snapshot["streams"][0]["offers"][0] == {
            "offer_id": 7,
            "share": 100,
            "state": "Pending",
            "name": "Test offer",
            "pinned": False,
        }
    engine.dispose()


def test_pinned_share_stays_fixed_and_other_shares_are_even():
    stream = DraftStream(
        id=52,
        name="Offer",
        offers=[
            DraftOffer(offer_id=1, share=40, state="active", pinned=True),
            DraftOffer(offer_id=2, share=10, state="Pending"),
            DraftOffer(offer_id=3, share=50, state="active"),
            DraftOffer(offer_id=4, share=20, state="Removed", pinned=True),
        ],
    )
    stream.redistribute_shares()
    assert [offer.share for offer in stream.offers] == [40, 30, 30, 20]
    stream.offers[2].state = "Removed"
    stream.redistribute_shares()
    assert [offer.share for offer in stream.offers] == [40, 60, 30, 20]


@pytest.mark.parametrize("outcome", ["success", "conflict", "denied"])
def test_sync_publishes_only_active_offers_and_keeps_draft(tmp_path, outcome):
    database_url = f"sqlite:///{tmp_path / 'sync.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    remote = [{"offer_id": 7, "share": 100, "state": "active"}]
    writes = []

    def stream():
        return {"id": 52, "name": "Offer", "schema": "landings", "offers": remote}

    def tracker(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/admin_api/v1/")
        if request.method == "PUT":
            assert path == "streams/52"
            writes.append(json.loads(request.content))
            if outcome == "denied":
                return httpx.Response(403)
            remote[:] = writes[-1]["offers"]
            return httpx.Response(200)
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "campaigns/42": {"id": 42, "name": "Campaign", "state": "active"},
                "campaigns/42/streams": [stream()],
                "streams/52": stream(),
                "offers": [{"id": 7, "name": "Test offer", "state": "active"}],
                "offers/7": {"id": 7, "name": "Test offer", "state": "active"},
                "offers/9": {"id": 9, "name": "New offer", "state": "active"},
            }[path],
        )

    app = create_app(database_url)
    with httpx.Client(
        base_url="https://tracker.example.com/admin_api/v1/",
        transport=httpx.MockTransport(tracker),
    ) as http:
        app.dependency_overrides[get_keitaro_client] = lambda: KeitaroClient(http)
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            path = "/campaigns/42/draft"
            target = {"offer_id": 7, "stream_id": 52}
            unsaved = client.get("/campaigns/42")
            assert 'value="sync"' not in unsaved.text
            assert client.post(path, data={"action": "refetch"}).status_code == 200
            removed = client.post(path, data={"action": "remove", **target})
            assert 'class="campaign-sync"' in removed.text
            assert 'value="sync"' in removed.text
            assert writes == []
            if outcome != "success":
                added = client.post(
                    path, data={"action": "add", "offer_id": 9, "stream_id": 52}
                )
                assert added.text.count("campaign-offer--pending") == 1
            if outcome == "conflict":
                remote.append({"offer_id": 8, "share": 10, "state": "active"})
            result = client.post(path, data={"action": "sync"})
            if outcome != "success":
                assert "Офферы синхронизированы" not in result.text
                assert "set-cookie" not in result.headers
                assert (
                    client.get("/campaigns/42").text.count("campaign-offer--pending")
                    == 1
                )
            if outcome == "conflict":
                assert result.status_code == 409
                assert "изменились в Keitaro" in result.text
                assert writes == []
            elif outcome == "denied":
                assert result.status_code == 502
                assert "HTTP 403" in result.text
                assert len(remote) == 1
            else:
                assert result.status_code == 200
                assert result.history[0].headers["location"] == "/campaigns/42"
                assert "Офферы синхронизированы" in result.text
                assert "В потоках пока нет офферов." in result.text
                assert "Офферы синхронизированы" not in client.get("/campaigns/42").text
                assert (
                    "Офферы синхронизированы"
                    not in client.get("/campaigns/42?synced=true").text
                )
                assert 'class="campaign-sync"' not in result.text
                assert "Test offer" not in result.text
                assert remote == [] and writes == [{"offers": []}]
                assert client.post(path, data={"action": "sync"}).status_code == 200
                assert len(writes) == 1
                assert (
                    client.post(path, data={"action": "restore", **target}).status_code
                    == 409
                )
                assert (
                    client.post(path, data={"action": "add", **target}).status_code
                    == 200
                )
                locally_removed = client.post(path, data={"action": "remove", **target})
                assert "Test offer" not in locally_removed.text
                assert 'class="campaign-sync"' not in locally_removed.text
                cleaned = client.post(path, data={"action": "sync"})
                assert cleaned.status_code == 200
                assert "Test offer" not in cleaned.text
                assert len(writes) == 1
                assert (
                    client.post(path, data={"action": "add", **target}).status_code
                    == 200
                )
                assert client.post(path, data={"action": "sync"}).status_code == 200
                assert writes[-1] == {
                    "offers": [{"offer_id": 7, "share": 100, "state": "active"}]
                }

    with Session(engine) as db:
        offer = db.get(CampaignOfferDraft, 42).snapshot["streams"][0]["offers"][0]
        assert offer["state"] == ("active" if outcome == "success" else "Removed")
        assert "published" not in offer
        if outcome != "success":
            pending = db.get(CampaignOfferDraft, 42).snapshot["streams"][0]["offers"][1]
            assert pending["state"] == "Pending" and "published" not in pending
    engine.dispose()


def test_legacy_pending_addition_is_confirmed_only_by_an_active_assignment():
    row = {"offer_id": 7, "share": 100, "state": "active"}
    draft = DraftSnapshot.model_validate(
        {
            "streams": [
                {
                    "id": 52,
                    "name": "Offers",
                    "edited": True,
                    "offers": [{**row, "published": False}],
                    "published_offers": [],
                }
            ]
        }
    )
    stream = draft.streams[0]
    offer = stream.offers[0]
    assert offer.state == "Pending" and "published" not in offer.model_dump()
    assert draft.has_pending_changes

    for status in ("disabled", "active"):
        remote_row = {**row, "state": status}
        remote = DraftSnapshot.model_validate(
            {
                "streams": [
                    {
                        "id": 52,
                        "name": "Offers",
                        "offers": [remote_row],
                        "published_offers": [remote_row],
                    }
                ]
            }
        )
        draft.reconcile(remote)
        assert offer.state == ("Pending" if status == "disabled" else "active")
        assert draft.has_pending_changes == (status == "disabled")
