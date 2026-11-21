from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from adrobot.keitaro.client import KeitaroClient, KeitaroError

ResourceId = Annotated[int, Field(strict=True, gt=0)]


class CampaignSummary(BaseModel):
    id: ResourceId
    name: str
    state: str


campaign_list = TypeAdapter(list[CampaignSummary])


def create_campaign(
    keitaro: KeitaroClient,
    *,
    name: str,
    domain_id: int,
    group_id: int,
    traffic_source_id: int,
) -> int:
    try:
        result = keitaro.request_json(
            "POST",
            "campaigns",
            json={
                "name": name,
                "domain_id": domain_id,
                "group_id": str(group_id),
                "traffic_source_id": traffic_source_id,
                "alias": uuid4().hex,
                "type": "position",
                "state": "disabled",
            },
        )
    except KeitaroError as exc:
        if exc.status_code != 422:
            raise
        raise KeitaroError(
            f"{exc} Отправлены domain_id={domain_id}, group_id={group_id}, "
            f"traffic_source_id={traffic_source_id}.",
            status_code=422,
        ) from exc
    campaign_id = result.get("id") if isinstance(result, dict) else None
    if type(campaign_id) is not int or campaign_id <= 0:
        raise KeitaroError("Keitaro did not return a valid campaign ID")
    return campaign_id


def enable_campaign(keitaro: KeitaroClient, campaign_id: int) -> None:
    keitaro.request_json("POST", f"campaigns/{campaign_id}/enable")


def disable_campaign(keitaro: KeitaroClient, campaign_id: int) -> None:
    keitaro.request_json("POST", f"campaigns/{campaign_id}/disable")


def archive_campaign(keitaro: KeitaroClient, campaign_id: int) -> None:
    keitaro.request("DELETE", f"campaigns/{campaign_id}")


def get_campaign(keitaro: KeitaroClient, campaign_id: int) -> CampaignSummary:
    try:
        campaign = CampaignSummary.model_validate(
            keitaro.request_json("GET", f"campaigns/{campaign_id}")
        )
    except ValidationError as exc:
        raise KeitaroError("Keitaro вернул некорректные данные кампании.") from exc
    if campaign.id != campaign_id:
        raise KeitaroError("Keitaro вернул другой ID кампании.")
    return campaign


def list_campaigns(keitaro: KeitaroClient) -> list[CampaignSummary]:
    try:
        return campaign_list.validate_python(keitaro.request_json("GET", "campaigns"))
    except ValidationError as exc:
        raise KeitaroError("Keitaro вернул некорректный список кампаний.") from exc
