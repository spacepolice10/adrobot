"""Local Keitaro Admin API stand-in for exercising the Adrobot UI."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

MOCK_KEY = "adrobot-demo"


class CampaignInput(BaseModel):
    name: Annotated[str, Field(min_length=1)]
    alias: Annotated[str, Field(min_length=1)]
    domain_id: int
    group_id: int
    traffic_source_id: int
    type: Literal["position", "weight"] = "position"
    state: Literal["active", "disabled"] = "active"


class OfferLink(BaseModel):
    offer_id: int
    share: Annotated[int, Field(ge=0, le=100)]
    state: Literal["active", "disabled"] = "active"


class OfferList(BaseModel):
    offers: list[OfferLink]


class StreamInput(BaseModel):
    campaign_id: int
    name: str
    type: Literal["forced", "regular", "default"]
    position: int
    schema_: Literal["redirect", "landings", "action"] = Field(alias="schema")
    action_type: Annotated[str, Field(min_length=1)]
    action_payload: str | None = None
    state: Literal["active", "disabled"] = "active"
    filters: list[dict] = Field(default_factory=list)
    offers: list[OfferLink] = Field(default_factory=list)
    collect_clicks: bool = False


class OfferInput(BaseModel):
    name: Annotated[str, Field(min_length=1)]
    offer_type: Literal["external"] = "external"
    action_type: str
    action_payload: Annotated[str, Field(min_length=1)]
    state: Literal["active"] = "active"


def require_key(api_key: Annotated[str | None, Header()] = None) -> None:
    if api_key != MOCK_KEY:
        raise HTTPException(401, "Use the local mock API key.")


def create_mock_app() -> FastAPI:
    app = FastAPI(title="Keitaro Admin API mock")
    api = APIRouter(prefix="/admin_api/v1", dependencies=[Depends(require_key)])
    domain = {"id": 1813, "name": "in.posdk.xyz", "state": "active"}
    group = {"id": 2, "name": "FORTESTS"}
    source = {"id": 3, "name": "FORTESTS"}
    offers = {
        offer_id: {
            "id": offer_id,
            "name": f"Demo Offer {suffix}",
            "state": "active",
            "action_type": "http",
            "action_payload": f"https://example.com/offers/{offer_id}",
        }
        for offer_id, suffix in enumerate("ABCDEFGHIJKL", start=7)
    }
    campaigns = {
        42: {
            "id": 42,
            "name": "Demo campaign",
            "alias": "demo",
            "state": "active",
            "type": "position",
            "domain_id": domain["id"],
            "group_id": group["id"],
            "traffic_source_id": source["id"],
        }
    }
    streams = {
        51: {
            "id": 51,
            "campaign_id": 42,
            "name": "Google",
            "schema": "redirect",
            "type": "forced",
            "position": 1,
            "state": "active",
            "action_type": "http",
            "action_payload": "https://google.com",
            "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
            "offers": [],
        },
        52: {
            "id": 52,
            "campaign_id": 42,
            "name": "Offer",
            "schema": "landings",
            "type": "default",
            "position": 2,
            "state": "active",
            "action_type": "http",
            "offers": [{"offer_id": 7, "share": 100, "state": "active"}],
        },
    }

    def lookup(records: dict[int, dict], resource_id: int) -> dict:
        item = records.get(resource_id)
        if item is None or item.get("state") == "deleted":
            raise HTTPException(404, "Resource not found.")
        return item

    def validate_links(links: list[OfferLink]) -> list[dict]:
        ids = {offer.offer_id for offer in links}
        if len(ids) != len(links) or not ids.issubset(offers):
            raise HTTPException(422, "Offers must be unique IDs from the catalog.")
        active = [offer for offer in links if offer.state == "active"]
        if active and sum(offer.share for offer in active) != 100:
            raise HTTPException(422, "Active shares must add up to 100.")
        return [offer.model_dump() for offer in links]

    @api.get("/domains")
    async def list_domains() -> list[dict]:
        return [domain]

    @api.get("/domains/{domain_id}")
    async def get_domain(domain_id: int) -> dict:
        return lookup({domain["id"]: domain}, domain_id)

    @api.get("/groups")
    async def list_groups(type: str = "campaigns") -> list[dict]:
        return [group] if type == "campaigns" else []

    @api.get("/traffic_sources")
    async def list_sources() -> list[dict]:
        return [source]

    @api.get("/offers")
    async def list_offers() -> list[dict]:
        return list(offers.values())

    @api.get("/offers/{offer_id}")
    async def get_offer(offer_id: int) -> dict:
        return lookup(offers, offer_id)

    @api.post("/offers")
    async def create_offer(data: OfferInput) -> dict:
        offer_id = max(offers) + 1
        offers[offer_id] = {"id": offer_id, **data.model_dump()}
        return offers[offer_id]

    @api.get("/campaigns")
    async def list_campaigns() -> list[dict]:
        return [
            campaign
            for campaign in campaigns.values()
            if campaign["state"] != "deleted"
        ]

    @api.get("/campaigns/{campaign_id}")
    async def get_campaign(campaign_id: int) -> dict:
        return lookup(campaigns, campaign_id)

    @api.post("/campaigns", status_code=201)
    async def create_campaign(data: CampaignInput) -> dict:
        if (data.domain_id, data.group_id, data.traffic_source_id) != (
            domain["id"],
            group["id"],
            source["id"],
        ):
            raise HTTPException(422, "Unknown domain, group, or traffic source.")
        if any(item["alias"] == data.alias for item in campaigns.values()):
            raise HTTPException(422, "Campaign alias already exists.")
        campaign_id = max(campaigns) + 1
        campaigns[campaign_id] = {"id": campaign_id, **data.model_dump()}
        return campaigns[campaign_id]

    @api.post("/campaigns/{campaign_id}/{action}")
    async def change_campaign_state(
        campaign_id: int, action: Literal["enable", "disable"]
    ) -> dict:
        campaign = lookup(campaigns, campaign_id)
        campaign["state"] = "active" if action == "enable" else "disabled"
        return campaign

    @api.delete("/campaigns/{campaign_id}", status_code=201)
    async def archive_campaign(campaign_id: int) -> Response:
        lookup(campaigns, campaign_id)["state"] = "deleted"
        return Response(status_code=201)

    @api.get("/campaigns/{campaign_id}/streams")
    async def list_campaign_streams(campaign_id: int) -> list[dict]:
        lookup(campaigns, campaign_id)
        return [
            stream
            for stream in streams.values()
            if stream["campaign_id"] == campaign_id
        ]

    @api.get("/streams/{stream_id}")
    async def get_stream(stream_id: int) -> dict:
        stream = lookup(streams, stream_id)
        lookup(campaigns, stream["campaign_id"])
        return stream

    @api.post("/streams")
    async def create_stream(data: StreamInput) -> dict:
        lookup(campaigns, data.campaign_id)
        if data.schema_ == "redirect" and not data.action_payload:
            raise HTTPException(422, "A redirect stream requires a URL.")
        stream_id = max(streams) + 1
        links = validate_links(data.offers)
        streams[stream_id] = {
            "id": stream_id,
            **data.model_dump(by_alias=True, exclude={"offers"}),
            "offers": links,
        }
        return streams[stream_id]

    @api.put("/streams/{stream_id}")
    async def replace_stream_offers(stream_id: int, data: OfferList) -> dict:
        stream = lookup(streams, stream_id)
        lookup(campaigns, stream["campaign_id"])
        if stream["schema"] != "landings":
            raise HTTPException(422, "Only an offer stream accepts offers.")
        stream["offers"] = validate_links(data.offers)
        return stream

    app.include_router(api)
    return app


app = create_mock_app()
