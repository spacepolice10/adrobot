from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from adrobot.keitaro import (
    KeitaroClient,
    KeitaroConfigurationError,
    KeitaroError,
    configured_client,
)

router = APIRouter(tags=["Campaigns"])
CAMPAIGN_FORM = Path(__file__).parent / "static" / "campaign_new.html"
ResourceId = Annotated[int, Field(strict=True, gt=0)]


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    domain_id: ResourceId
    group_id: ResourceId
    traffic_source_id: ResourceId


class CampaignCreated(BaseModel):
    id: ResourceId


def get_keitaro_client() -> Iterator[KeitaroClient]:
    try:
        with configured_client() as client:
            yield client
    except KeitaroConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/campaigns/new", include_in_schema=False)
def new_campaign() -> FileResponse:
    return FileResponse(CAMPAIGN_FORM, media_type="text/html")


@router.post(
    "/api/campaigns",
    status_code=201,
    responses={
        502: {"description": "Keitaro request failed"},
        503: {"description": "Keitaro integration is unavailable"},
    },
)
def post_campaign(
    data: CampaignCreate,
    keitaro: Annotated[KeitaroClient, Depends(get_keitaro_client)],
) -> CampaignCreated:
    try:
        result = keitaro.request_json(
            "POST",
            "campaigns",
            json={
                "name": data.name,
                "domain_id": data.domain_id,
                "group_id": str(data.group_id),
                "traffic_source_id": data.traffic_source_id,
                "alias": uuid4().hex,
                "type": "position",
                "state": "disabled",
            },
        )
    except KeitaroError as exc:
        raise HTTPException(502, str(exc)) from exc

    try:
        return CampaignCreated.model_validate(result)
    except ValidationError as exc:
        raise HTTPException(502, "Keitaro did not return a valid campaign ID") from exc
