from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.orm import Session

from adrobot.keitaro import KeitaroClient
from adrobot.models.offer_draft import CampaignOfferDraft


class OfferForm(BaseModel):
    action: Literal["add", "remove", "restore", "pin", "unpin", "refetch", "sync"]
    stream_id: Annotated[int, Field(gt=0)] | None = None
    offer_id: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def validate_action_target(self) -> Self:
        if self.action not in {"refetch", "sync"} and (
            self.stream_id is None or self.offer_id is None
        ):
            raise PydanticCustomError("missing_offer_target", "Выберите поток и оффер.")
        return self

    def submit(self, db: Session, keitaro: KeitaroClient, campaign_id: int) -> None:
        if self.action == "refetch":
            CampaignOfferDraft.refresh(db, keitaro, campaign_id)
            return
        if self.action == "sync":
            CampaignOfferDraft.publish(db, keitaro, campaign_id)
            return

        edits = {
            "add": CampaignOfferDraft.add_offer,
            "remove": CampaignOfferDraft.remove_offer,
            "restore": CampaignOfferDraft.restore_offer,
            "pin": CampaignOfferDraft.pin_offer,
            "unpin": CampaignOfferDraft.unpin_offer,
        }
        assert self.stream_id is not None and self.offer_id is not None
        edits[self.action](
            db, keitaro, campaign_id, stream_id=self.stream_id, offer_id=self.offer_id
        )
