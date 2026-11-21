from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from adrobot.keitaro import KeitaroClient, KeitaroError
from adrobot.keitaro.campaign_resources import (
    resolve_campaign_domain_id,
    resolve_campaign_group_id,
    resolve_traffic_source_id,
)
from adrobot.keitaro.campaigns import create_campaign, enable_campaign
from adrobot.keitaro.streams import create_campaign_streams
from adrobot.settings import Settings


class CampaignForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    country_code: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z]{2}$", to_upper=True)
    ]
    offer_id: Annotated[int, Field(gt=0)]

    def submit(self, keitaro: KeitaroClient, settings: Settings) -> int:
        domain_id = resolve_campaign_domain_id(
            keitaro,
            settings.keitaro_campaign_domain_id,
            settings.keitaro_campaign_domain,
        )
        group_id = resolve_campaign_group_id(keitaro, "FORTESTS")
        traffic_source_id = resolve_traffic_source_id(keitaro, "FORTESTS")

        campaign_id = create_campaign(
            keitaro,
            name=self.name,
            domain_id=domain_id,
            group_id=group_id,
            traffic_source_id=traffic_source_id,
        )
        create_campaign_streams(
            keitaro,
            campaign_id=campaign_id,
            country_code=self.country_code,
            offer_id=self.offer_id,
        )
        try:
            enable_campaign(keitaro, campaign_id)
        except KeitaroError as exc:
            raise KeitaroError(
                f"Campaign {campaign_id}: could not confirm activation. {exc}"
            ) from exc
        return campaign_id
