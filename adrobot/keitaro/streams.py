from typing import Annotated

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from adrobot.keitaro.client import KeitaroClient, KeitaroError
from adrobot.keitaro.offers import list_offers


class StreamOffer(BaseModel):
    offer_id: Annotated[int, Field(strict=True, gt=0)]
    share: int
    state: str


class CampaignStream(BaseModel):
    id: Annotated[int, Field(strict=True, gt=0)]
    name: str
    flow_schema: str | None = Field(default=None, validation_alias="schema")
    offers: list[StreamOffer] = Field(default_factory=list)


stream_list = TypeAdapter(list[CampaignStream])


def list_campaign_streams(
    keitaro: KeitaroClient, campaign_id: int
) -> list[CampaignStream]:
    try:
        return stream_list.validate_python(
            keitaro.request_json("GET", f"campaigns/{campaign_id}/streams")
        )
    except ValidationError as exc:
        raise KeitaroError("Keitaro returned an invalid stream list") from exc


def is_offer_stream(stream: CampaignStream) -> bool:
    return stream.flow_schema == "landings" or (
        stream.flow_schema is None and bool(stream.offers)
    )


def fetch_streams_with_offer_names(
    keitaro: KeitaroClient, campaign_id: int
) -> tuple[list[CampaignStream], dict[int, str] | None]:
    """Fetch the campaign streams. The name map is None if the offer catalog is unavailable."""
    streams = list_campaign_streams(keitaro, campaign_id)
    if not any(stream.offers for stream in streams):
        return streams, {}
    try:
        names = {offer.id: offer.name for offer in list_offers(keitaro)}
    except KeitaroError:
        return streams, None
    return streams, names


def replace_stream_offers(
    keitaro: KeitaroClient, stream_id: int, offers: list[StreamOffer]
) -> list[StreamOffer]:
    keitaro.request(
        "PUT",
        f"streams/{stream_id}",
        json={"offers": [offer.model_dump() for offer in offers]},
    )
    try:
        stream = CampaignStream.model_validate(
            keitaro.request_json("GET", f"streams/{stream_id}")
        )
    except ValidationError as exc:
        raise KeitaroError("Keitaro не подтвердил состав потока.") from exc
    if stream.id != stream_id:
        raise KeitaroError("Keitaro вернул другой ID потока.")
    return stream.offers


def create_campaign_streams(
    keitaro: KeitaroClient,
    *,
    campaign_id: int,
    country_code: str,
    offer_id: int,
) -> None:
    streams = (
        {
            "name": "Google",
            "type": "forced",
            "position": 1,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://google.com",
            "filters": [
                {
                    "name": "country",
                    "mode": "accept",
                    "payload": [country_code.upper()],
                }
            ],
        },
        {
            "name": "Offer",
            "type": "default",
            "position": 2,
            "schema": "landings",
            "action_type": "http",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        },
    )
    for stream in streams:
        try:
            keitaro.request_json(
                "POST",
                "streams",
                json={
                    **stream,
                    "campaign_id": campaign_id,
                    "state": "active",
                    "collect_clicks": True,
                },
            )
        except KeitaroError as exc:
            raise KeitaroError(
                f"Campaign {campaign_id}: could not create the {stream['name']} stream. {exc}",
            ) from exc
